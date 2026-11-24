"""Shared LangGraph execution engine supporting Human-in-the-Loop, SSE streaming & usage telemetry."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from nexus.llm import flush_langfuse, get_langfuse_callbacks
from nexus.storage import MissionControlStore
from nexus.telemetry import UsageTrackingCallback

logger = logging.getLogger(__name__)

# Global optional store reference attached during FastAPI lifespan so Discord + Scheduler also log tokens
_active_store: MissionControlStore | None = None


def set_active_store(store: MissionControlStore | None) -> None:
    global _active_store
    _active_store = store


@dataclass
class TurnResult:
    status: str  # "completed" | "approval_required"
    reply: str
    thread_id: str
    pending_approval: dict[str, Any] | None = None


def _extract_pending_interrupt(state_snapshot: Any) -> dict[str, Any] | None:
    """Inspect a LangGraph StateSnapshot and return the first pending interrupt payload."""
    tasks = getattr(state_snapshot, "tasks", None) or ()
    for task in tasks:
        interrupts = getattr(task, "interrupts", None) or ()
        if interrupts:
            value = interrupts[0].value
            return value if isinstance(value, dict) else {"message": str(value)}
    return None


def _extract_last_ai_reply(state_snapshot: Any) -> str:
    """Return the latest non-empty AI message content from the graph state."""
    values = getattr(state_snapshot, "values", {}) or {}
    messages = values.get("messages", [])
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai" and msg.content:
            return msg.content if isinstance(msg.content, str) else str(msg.content)
    return "Tâche terminée."


def _build_run_config(
    thread_id: str,
    user_id: str | None = None,
    store: MissionControlStore | None = None,
) -> dict[str, Any]:
    callbacks = get_langfuse_callbacks(session_id=thread_id, user_id=user_id)
    effective_store = store or _active_store
    if effective_store is not None:
        callbacks.append(UsageTrackingCallback(store=effective_store, thread_id=thread_id))
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": user_id or "nexus-user",
        },
        "recursion_limit": 50,
    }


def _describe_update_event(node_name: str, payload: Any) -> dict[str, Any]:
    """Build a concise real-time progress event for the Mission Control chat UI."""
    detail = ""
    if isinstance(payload, dict):
        if "next_agent" in payload:
            nxt = payload["next_agent"]
            detail = (
                "Rédaction de la réponse finale..." if nxt == "FINISH" else f"Délégation → `{nxt}`"
            )
        elif "messages" in payload and payload["messages"]:
            last = payload["messages"][-1]
            tool_calls = getattr(last, "tool_calls", None) or []
            if tool_calls:
                names = ", ".join(tc.get("name", "outil") for tc in tool_calls[:3])
                detail = f"Appel outil : `{names}`"
            elif getattr(last, "type", None) == "tool":
                detail = f"Résultat reçu (`{getattr(last, 'name', 'outil')}`)"
            else:
                detail = f"Traitement terminé par `{node_name}`"
    return {"type": "step", "node": node_name, "detail": detail or f"Exécution de `{node_name}`"}


async def get_thread_history(graph: Any, thread_id: str) -> dict[str, Any]:
    """Return user/assistant messages and any pending HITL interrupt for a thread."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    values = getattr(snapshot, "values", {}) or {}
    raw_messages = values.get("messages", [])

    formatted: list[dict[str, Any]] = []
    for msg in raw_messages:
        mtype = getattr(msg, "type", "")
        content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
        if mtype == "human" and content.strip():
            formatted.append({"role": "user", "content": content})
        elif mtype == "ai" and content.strip():
            # Skip intermediate tool-call-only assistant messages when empty
            formatted.append(
                {
                    "role": "assistant",
                    "content": content,
                    "agent": getattr(msg, "name", None) or "supervisor",
                }
            )

    return {
        "thread_id": thread_id,
        "messages": formatted,
        "pending_approval": _extract_pending_interrupt(snapshot),
    }


async def run_turn(
    graph: Any,
    thread_id: str,
    user_message: str,
    user_id: str | None = None,
    store: MissionControlStore | None = None,
) -> TurnResult:
    """Run a user or scheduled prompt through the Nexus LangGraph."""
    config = _build_run_config(thread_id=thread_id, user_id=user_id, store=store)
    effective_store = store or _active_store
    if effective_store is not None:
        await effective_store.touch_thread(thread_id, auto_title=user_message[:56])

    try:
        await graph.ainvoke(
            {"messages": [HumanMessage(content=user_message)], "step_count": 0},
            config=config,
        )
    finally:
        flush_langfuse()
    snapshot = await graph.aget_state(config)
    pending = _extract_pending_interrupt(snapshot)
    if pending:
        return TurnResult(
            status="approval_required",
            reply=pending.get("message", "Validation requise avant de continuer."),
            thread_id=thread_id,
            pending_approval=pending,
        )
    return TurnResult(
        status="completed",
        reply=_extract_last_ai_reply(snapshot),
        thread_id=thread_id,
    )


async def resume_turn(
    graph: Any,
    thread_id: str,
    approved: bool,
    reason: str = "",
    user_id: str | None = None,
    store: MissionControlStore | None = None,
) -> TurnResult:
    """Resume an interrupted LangGraph thread with the user's HITL decision."""
    config = _build_run_config(thread_id=thread_id, user_id=user_id, store=store)
    decision: dict[str, Any] = {"approved": approved}
    if reason:
        decision["reason"] = reason

    try:
        await graph.ainvoke(Command(resume=decision), config=config)
    finally:
        flush_langfuse()
    snapshot = await graph.aget_state(config)
    pending = _extract_pending_interrupt(snapshot)
    if pending:
        return TurnResult(
            status="approval_required",
            reply=pending.get("message", "Une autre validation est requise."),
            thread_id=thread_id,
            pending_approval=pending,
        )
    return TurnResult(
        status="completed",
        reply=_extract_last_ai_reply(snapshot),
        thread_id=thread_id,
    )


async def stream_turn(
    graph: Any,
    thread_id: str,
    user_message: str,
    user_id: str | None = None,
    store: MissionControlStore | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream real-time agent steps and final/HITL outcome as JSON-serializable events."""
    config = _build_run_config(thread_id=thread_id, user_id=user_id, store=store)
    effective_store = store or _active_store
    if effective_store is not None:
        await effective_store.touch_thread(thread_id, auto_title=user_message[:56])

    try:
        async for chunk in graph.astream(
            {"messages": [HumanMessage(content=user_message)], "step_count": 0},
            config=config,
            stream_mode="updates",
        ):
            if isinstance(chunk, dict):
                for node_name, payload in chunk.items():
                    if node_name == "__interrupt__":
                        continue
                    yield _describe_update_event(node_name, payload)
    finally:
        flush_langfuse()

    snapshot = await graph.aget_state(config)
    pending = _extract_pending_interrupt(snapshot)
    if pending:
        yield {
            "type": "approval_required",
            "thread_id": thread_id,
            "reply": pending.get("message", "Validation requise avant de continuer."),
            "pending_approval": pending,
        }
        return

    yield {
        "type": "done",
        "thread_id": thread_id,
        "reply": _extract_last_ai_reply(snapshot),
    }


async def stream_resume_turn(
    graph: Any,
    thread_id: str,
    approved: bool,
    reason: str = "",
    user_id: str | None = None,
    store: MissionControlStore | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a resumed HITL LangGraph execution."""
    config = _build_run_config(thread_id=thread_id, user_id=user_id, store=store)
    decision: dict[str, Any] = {"approved": approved}
    if reason:
        decision["reason"] = reason

    try:
        async for chunk in graph.astream(
            Command(resume=decision),
            config=config,
            stream_mode="updates",
        ):
            if isinstance(chunk, dict):
                for node_name, payload in chunk.items():
                    if node_name == "__interrupt__":
                        continue
                    yield _describe_update_event(node_name, payload)
    finally:
        flush_langfuse()

    snapshot = await graph.aget_state(config)
    pending = _extract_pending_interrupt(snapshot)
    if pending:
        yield {
            "type": "approval_required",
            "thread_id": thread_id,
            "reply": pending.get("message", "Une autre validation est requise."),
            "pending_approval": pending,
        }
        return

    yield {
        "type": "done",
        "thread_id": thread_id,
        "reply": _extract_last_ai_reply(snapshot),
    }
