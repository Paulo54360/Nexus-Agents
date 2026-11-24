"""FastAPI entrypoint hosting Mission Control API, SSE streams, Discord bot, and scheduler."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field

from nexus.automations.engine import AutomationEngine
from nexus.config import get_settings
from nexus.graph.builder import build_nexus_graph
from nexus.interfaces.discord_bot import NexusDiscordBot
from nexus.mcp.registry import load_tools_by_domain
from nexus.runtime import (
    get_thread_history,
    resume_turn,
    run_turn,
    set_active_store,
    stream_resume_turn,
    stream_turn,
)
from nexus.scheduler.jobs import build_scheduler
from nexus.storage import MissionControlStore
from nexus.telemetry import log_broadcaster

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
# Attach live SSE log broadcaster to root logger once
root_logger = logging.getLogger()
if log_broadcaster not in root_logger.handlers:
    log_broadcaster.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    root_logger.addHandler(log_broadcaster)

logger = logging.getLogger(__name__)

CHAT_REQUESTS = Counter("nexus_chat_requests_total", "Total chat turns processed by Nexus")
HITL_DECISIONS = Counter("nexus_hitl_decisions_total", "HITL approval decisions", ["decision"])


class ChatRequest(BaseModel):
    thread_id: str = "default-http"
    message: str


class StreamMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ApprovalRequest(BaseModel):
    approved: bool
    reason: str = ""


class CreateThreadRequest(BaseModel):
    title: str = "Nouvelle conversation"
    category: str = "general"


class RenameThreadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    category: str | None = None


class TurnResponse(BaseModel):
    status: str
    thread_id: str
    reply: str
    pending_approval: dict[str, Any] | None = None


def _parse_litellm_cascade(
    config_path: Path = Path("config/litellm_config.yaml"),
) -> dict[str, Any]:
    """Read configured model aliases and fallback cascade from litellm_config.yaml."""
    if not config_path.exists():
        return {"models": [], "fallbacks": []}
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        grouped: dict[str, list[str]] = {}
        for item in raw.get("model_list", []):
            alias = str(item.get("model_name", "unknown"))
            target = str((item.get("litellm_params") or {}).get("model", "unknown"))
            grouped.setdefault(alias, []).append(target)
        models = [{"alias": alias, "targets": targets} for alias, targets in grouped.items()]
        fallbacks = raw.get("router_settings", {}).get("fallbacks", [])
        return {"models": models, "fallbacks": fallbacks}
    except Exception as exc:
        logger.warning("Failed to parse litellm_config.yaml: %s", exc)
        return {"models": [], "fallbacks": []}


def _parse_mcp_servers(config_path: Path) -> list[dict[str, Any]]:
    """Read MCP server metadata without exposing secret values."""
    if not config_path.exists():
        return []
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        servers: list[dict[str, Any]] = []
        for name, cfg in (raw.get("servers") or {}).items():
            servers.append(
                {
                    "name": name,
                    "agent": cfg.get("agent", "general"),
                    "enabled": bool(cfg.get("enabled", False)),
                    "transport": cfg.get("transport", "stdio"),
                    "command": cfg.get("command", ""),
                }
            )
        return servers
    except Exception as exc:
        logger.warning("Failed to parse mcp_servers.yaml: %s", exc)
        return []


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Postgres checkpointer, Mission Control store, MCP tools, LangGraph, Discord & scheduler."""
    pool = None
    checkpointer = None
    discord_task: asyncio.Task | None = None
    discord_bot: NexusDiscordBot | None = None

    if settings.database_url:
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                max_size=10,
                kwargs={"autocommit": True, "prepare_threshold": 0},
                open=False,
            )
            await pool.open()
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            logger.info("LangGraph AsyncPostgresSaver initialized.")
        except Exception as exc:
            logger.warning(
                "Postgres unavailable (%s); falling back to in-memory checkpointer.", exc
            )
            pool = None

    store = MissionControlStore(pool=pool)
    await store.ensure_schema()
    set_active_store(store)
    app.state.store = store
    app.state.postgres_connected = pool is not None
    app.state.started_at = datetime.now(UTC).isoformat()

    bot_holder: dict[str, NexusDiscordBot | None] = {"bot": None}
    tools_by_domain = await load_tools_by_domain()
    app.state.tools_by_domain = tools_by_domain

    graph = build_nexus_graph(
        tools_by_domain=tools_by_domain,
        checkpointer=checkpointer,
        get_discord_bot=lambda: bot_holder["bot"],
    )
    app.state.graph = graph

    automation_engine = AutomationEngine(graph=graph)
    app.state.automation_engine = automation_engine

    if settings.discord_bot_token:
        discord_bot = NexusDiscordBot(graph=graph, automation_engine=automation_engine)
        bot_holder["bot"] = discord_bot
        automation_engine.attach_bot(discord_bot)
        discord_task = asyncio.create_task(discord_bot.start(settings.discord_bot_token))
        logger.info("Discord bot background task started.")
    else:
        logger.info("DISCORD_BOT_TOKEN not set — running HTTP API & scheduler without Discord.")
    app.state.discord_bot = discord_bot

    scheduler = build_scheduler(graph=graph, discord_bot=discord_bot)
    automation_engine.register_cron_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Proactive APScheduler started.")

    try:
        yield
    finally:
        set_active_store(None)
        scheduler.shutdown(wait=False)
        if discord_bot:
            await discord_bot.close()
        if discord_task:
            discord_task.cancel()
        if pool:
            await pool.close()


app = FastAPI(
    title="Nexus Multi-Agent Mission Control",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|nexus-vps|[a-z0-9-]+\.[a-z0-9-]+\.ts\.net)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_store() -> MissionControlStore:
    store = getattr(app.state, "store", None)
    if store is None:
        store = MissionControlStore(pool=None)
        app.state.store = store
    return store


def _get_graph() -> Any:
    graph = getattr(app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")
    return graph


# ------------------------------------------------------------------------------
# Health, Metrics & Classic HTTP Endpoints
# ------------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    bot = getattr(app.state, "discord_bot", None)
    return {
        "status": "ok",
        "env": settings.nexus_env,
        "mock_tools": str(settings.mock_tools),
        "postgres": bool(getattr(app.state, "postgres_connected", False)),
        "discord_ready": bool(bot and bot.is_ready()),
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chat", response_model=TurnResponse)
async def chat(payload: ChatRequest) -> TurnResponse:
    graph = _get_graph()
    CHAT_REQUESTS.inc()
    result = await run_turn(
        graph,
        thread_id=payload.thread_id,
        user_message=payload.message,
        store=_get_store(),
    )
    return TurnResponse(
        status=result.status,
        thread_id=result.thread_id,
        reply=result.reply,
        pending_approval=result.pending_approval,
    )


@app.post("/approvals/{thread_id}", response_model=TurnResponse)
async def approve(thread_id: str, payload: ApprovalRequest) -> TurnResponse:
    graph = _get_graph()
    HITL_DECISIONS.labels(decision="approved" if payload.approved else "rejected").inc()
    result = await resume_turn(
        graph,
        thread_id=thread_id,
        approved=payload.approved,
        reason=payload.reason,
        store=_get_store(),
    )
    return TurnResponse(
        status=result.status,
        thread_id=result.thread_id,
        reply=result.reply,
        pending_approval=result.pending_approval,
    )


# ------------------------------------------------------------------------------
# Mission Control — Multi-Chat Threads & SSE Streaming
# ------------------------------------------------------------------------------


@app.get("/api/threads")
async def list_threads() -> dict[str, Any]:
    threads = await _get_store().list_threads()
    return {"threads": threads}


@app.post("/api/threads")
async def create_thread(payload: CreateThreadRequest) -> dict[str, Any]:
    thread = await _get_store().create_thread(title=payload.title, category=payload.category)
    return {"thread": thread}


@app.patch("/api/threads/{thread_id}")
async def rename_thread(thread_id: str, payload: RenameThreadRequest) -> dict[str, Any]:
    updated = await _get_store().rename_thread(
        thread_id=thread_id, title=payload.title, category=payload.category
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"thread": updated}


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict[str, Any]:
    deleted = await _get_store().delete_thread(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"deleted": True, "thread_id": thread_id}


@app.get("/api/threads/{thread_id}/messages")
async def thread_messages(thread_id: str) -> dict[str, Any]:
    graph = _get_graph()
    return await get_thread_history(graph, thread_id=thread_id)


@app.post("/api/threads/{thread_id}/stream")
async def stream_thread_message(thread_id: str, payload: StreamMessageRequest) -> StreamingResponse:
    graph = _get_graph()
    store = _get_store()
    CHAT_REQUESTS.inc()

    async def event_generator():
        try:
            async for event in stream_turn(
                graph,
                thread_id=thread_id,
                user_message=payload.message,
                user_id="web-mission-control",
                store=store,
            ):
                yield _sse(event)
        except Exception as exc:
            logger.exception("SSE stream_turn failed for thread %s", thread_id)
            yield _sse({"type": "error", "message": f"Erreur lors du traitement : {exc}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/threads/{thread_id}/approve/stream")
async def stream_thread_approval(thread_id: str, payload: ApprovalRequest) -> StreamingResponse:
    graph = _get_graph()
    store = _get_store()
    HITL_DECISIONS.labels(decision="approved" if payload.approved else "rejected").inc()

    async def event_generator():
        try:
            async for event in stream_resume_turn(
                graph,
                thread_id=thread_id,
                approved=payload.approved,
                reason=payload.reason,
                user_id="web-mission-control",
                store=store,
            ):
                yield _sse(event)
        except Exception as exc:
            logger.exception("SSE stream_resume_turn failed for thread %s", thread_id)
            yield _sse({"type": "error", "message": f"Erreur lors de la reprise HITL : {exc}"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------------------
# Mission Control — FinOps Token Usage Telemetry
# ------------------------------------------------------------------------------


@app.get("/api/stats/usage")
async def stats_usage(days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    return await _get_store().get_usage_stats(days=days)


# ------------------------------------------------------------------------------
# Mission Control — Live Architecture & MCP Inventory
# ------------------------------------------------------------------------------


@app.get("/api/architecture")
async def architecture_topology() -> dict[str, Any]:
    tools_by_domain: dict[str, list[Any]] = getattr(app.state, "tools_by_domain", {}) or {}
    bot = getattr(app.state, "discord_bot", None)
    scheduler = getattr(app.state, "scheduler", None)
    automation_engine: AutomationEngine | None = getattr(app.state, "automation_engine", None)

    gmail_tools = [
        {"name": t.name, "description": (t.description or "").strip().splitlines()[0][:140]}
        for t in tools_by_domain.get("gmail", [])
    ]
    prod_tools = [
        {"name": t.name, "description": (t.description or "").strip().splitlines()[0][:140]}
        for t in tools_by_domain.get("productivity", [])
    ]
    asso_tools = [
        {
            "name": "discord_asso_list_channels",
            "description": "Liste les salons textuels & forums du serveur staff (lecture seule)",
        },
        {
            "name": "discord_asso_read_messages",
            "description": "Lit l'historique récent des salons textuels staff (lecture seule)",
        },
        {
            "name": "discord_asso_read_forum_posts",
            "description": "Lit les dossiers actifs & archivés des forums staff (lecture seule)",
        },
    ]

    litellm_info = _parse_litellm_cascade()
    mcp_servers = _parse_mcp_servers(settings.mcp_config_path)

    return {
        "system": {
            "env": settings.nexus_env,
            "started_at": getattr(app.state, "started_at", None),
            "mock_tools": settings.mock_tools,
            "postgres_connected": bool(getattr(app.state, "postgres_connected", False)),
            "discord_connected": bool(bot and bot.is_ready()),
            "discord_guilds": len(bot.guilds) if (bot and bot.is_ready()) else 0,
            "scheduler_running": bool(scheduler and scheduler.running),
            "scheduled_jobs": len(scheduler.get_jobs()) if scheduler else 0,
            "automations_enabled": (
                sum(1 for r in automation_engine.rules if r.enabled) if automation_engine else 0
            ),
            "total_tools": len(gmail_tools) + len(prod_tools) + len(asso_tools),
            "langfuse_enabled": bool(settings.langfuse_public_key and settings.langfuse_secret_key),
            "langfuse_host": settings.langfuse_host,
        },
        "agents": [
            {
                "id": "supervisor",
                "label": "Supervisor",
                "role": "Routage intelligent & synthèse finale Markdown",
                "model_tier": "nexus-fast → nexus-smart",
                "hitl": False,
                "tools": [],
                "status": "online",
            },
            {
                "id": "gmail_agent",
                "label": "Gmail Agent",
                "role": "Lecture, tri, brouillons & envoi Gmail sécurisé",
                "model_tier": "nexus-smart",
                "hitl": True,
                "tools": gmail_tools,
                "status": "online" if gmail_tools else "degraded",
            },
            {
                "id": "productivity_agent",
                "label": "Productivity Agent",
                "role": "Google Calendar multi-agendas & bases Notion (ToDo, LPA)",
                "model_tier": "nexus-smart",
                "hitl": True,
                "tools": prod_tools,
                "status": "online" if prod_tools else "degraded",
            },
            {
                "id": "asso_agent",
                "label": "Asso Monitor Agent",
                "role": "Veille passive & forums modération Discord (lecture seule)",
                "model_tier": "nexus-smart",
                "hitl": False,
                "tools": asso_tools,
                "status": "online" if (bot and bot.is_ready()) else "standby",
            },
        ],
        "mcp_servers": mcp_servers,
        "litellm": litellm_info,
    }


# ------------------------------------------------------------------------------
# Mission Control — Real-Time Logs Console (Ring Buffer + SSE)
# ------------------------------------------------------------------------------


@app.get("/api/logs/recent")
async def recent_logs(limit: int = Query(default=150, ge=1, le=400)) -> dict[str, Any]:
    return {"logs": log_broadcaster.recent(limit=limit)}


@app.get("/api/logs/stream")
async def stream_logs(request: Request) -> StreamingResponse:
    queue = log_broadcaster.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield _sse(entry)
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            log_broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ------------------------------------------------------------------------------
# Mission Control — Automations & Scheduled Jobs Manager
# ------------------------------------------------------------------------------


@app.get("/api/automations")
async def list_automations() -> dict[str, Any]:
    engine: AutomationEngine | None = getattr(app.state, "automation_engine", None)
    scheduler = getattr(app.state, "scheduler", None)
    jobs: list[dict[str, Any]] = []
    if scheduler:
        for job in scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "trigger": str(job.trigger),
                    "next_run_time": next_run.isoformat() if next_run else None,
                }
            )
    return {
        "rules": engine.list_rules_data() if engine else [],
        "scheduled_jobs": jobs,
    }


@app.post("/api/automations/{rule_id}/toggle")
async def toggle_automation(rule_id: str) -> dict[str, Any]:
    engine: AutomationEngine | None = getattr(app.state, "automation_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="AutomationEngine not initialized")
    updated = engine.toggle_rule(rule_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Automation rule not found")
    return {"rule": updated}


@app.post("/api/automations/{rule_id}/run")
async def run_automation(rule_id: str) -> dict[str, Any]:
    engine: AutomationEngine | None = getattr(app.state, "automation_engine", None)
    if not engine:
        raise HTTPException(status_code=503, detail="AutomationEngine not initialized")
    rule = next((r for r in engine.rules if r.id == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=404, detail="Automation rule not found")

    asyncio.create_task(engine.execute_rule(rule, context={}))
    return {"status": "triggered", "rule_id": rule_id}


@app.post("/api/automations/reload")
async def reload_automations() -> dict[str, Any]:
    engine: AutomationEngine | None = getattr(app.state, "automation_engine", None)
    scheduler = getattr(app.state, "scheduler", None)
    if not engine:
        raise HTTPException(status_code=503, detail="AutomationEngine not initialized")
    engine.reload()
    if scheduler:
        engine.register_cron_jobs(scheduler)
    return {"reloaded": True, "rules": engine.list_rules_data()}
