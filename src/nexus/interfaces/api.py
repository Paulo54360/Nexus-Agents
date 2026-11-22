"""FastAPI entrypoint hosting health/metrics endpoints, HTTP chat API, Discord bot, and scheduler."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel

from nexus.automations.engine import AutomationEngine
from nexus.config import get_settings
from nexus.graph.builder import build_nexus_graph
from nexus.interfaces.discord_bot import NexusDiscordBot
from nexus.mcp.registry import load_tools_by_domain
from nexus.runtime import resume_turn, run_turn
from nexus.scheduler.jobs import build_scheduler

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

CHAT_REQUESTS = Counter("nexus_chat_requests_total", "Total chat turns processed by Nexus")
HITL_DECISIONS = Counter("nexus_hitl_decisions_total", "HITL approval decisions", ["decision"])


class ChatRequest(BaseModel):
    thread_id: str = "default-http"
    message: str


class ApprovalRequest(BaseModel):
    approved: bool
    reason: str = ""


class TurnResponse(BaseModel):
    status: str
    thread_id: str
    reply: str
    pending_approval: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Postgres checkpointer, MCP tools, LangGraph, scheduler, and Discord bot."""
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

    bot_holder: dict[str, NexusDiscordBot | None] = {"bot": None}
    tools_by_domain = await load_tools_by_domain()
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

    scheduler = build_scheduler(graph=graph, discord_bot=discord_bot)
    automation_engine.register_cron_jobs(scheduler)
    scheduler.start()
    logger.info("Proactive APScheduler started.")

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        if discord_bot:
            await discord_bot.close()
        if discord_task:
            discord_task.cancel()
        if pool:
            await pool.close()


app = FastAPI(
    title="Nexus Multi-Agent Platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.nexus_env, "mock_tools": str(settings.mock_tools)}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/chat", response_model=TurnResponse)
async def chat(payload: ChatRequest) -> TurnResponse:
    graph = getattr(app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")

    CHAT_REQUESTS.inc()
    result = await run_turn(graph, thread_id=payload.thread_id, user_message=payload.message)
    return TurnResponse(
        status=result.status,
        thread_id=result.thread_id,
        reply=result.reply,
        pending_approval=result.pending_approval,
    )


@app.post("/approvals/{thread_id}", response_model=TurnResponse)
async def approve(thread_id: str, payload: ApprovalRequest) -> TurnResponse:
    graph = getattr(app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")

    HITL_DECISIONS.labels(decision="approved" if payload.approved else "rejected").inc()
    result = await resume_turn(
        graph,
        thread_id=thread_id,
        approved=payload.approved,
        reason=payload.reason,
    )
    return TurnResponse(
        status=result.status,
        thread_id=result.thread_id,
        reply=result.reply,
        pending_approval=result.pending_approval,
    )
