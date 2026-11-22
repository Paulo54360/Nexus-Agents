"""Shared LangGraph execution engine supporting Human-in-the-Loop (interrupt/resume)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from nexus.llm import flush_langfuse, get_langfuse_callbacks

logger = logging.getLogger(__name__)


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


async def run_turn(
    graph: Any,
    thread_id: str,
    user_message: str,
    user_id: str | None = None,
) -> TurnResult:
    """Run a user or scheduled prompt through the Nexus LangGraph."""
    callbacks = get_langfuse_callbacks(session_id=thread_id, user_id=user_id)
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": user_id or "nexus-user",
        },
        "recursion_limit": 50,
    }
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
) -> TurnResult:
    """Resume an interrupted LangGraph thread with the user's HITL decision."""
    callbacks = get_langfuse_callbacks(session_id=thread_id, user_id=user_id)
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
        "metadata": {
            "langfuse_session_id": thread_id,
            "langfuse_user_id": user_id or "nexus-user",
        },
        "recursion_limit": 50,
    }
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
