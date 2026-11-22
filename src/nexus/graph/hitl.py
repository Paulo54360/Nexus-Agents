"""Human-in-the-Loop (HITL) security policy & LangGraph interrupt() tool wrapper.

Policy agreed in architecture workshop:
- Autonomous: reading, searching, applying Gmail labels, creating drafts, managing personal Notion tasks.
- Approval required (Discord ✅/❌): sending/replying emails, deleting/trashing anything,
  creating/updating/deleting Google Calendar events, posting external messages.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

# High-impact action patterns that MUST pause for explicit user approval
_GATED_TOOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|_)send(_|$)"),
    re.compile(r"(^|_)reply(_|$)"),
    re.compile(r"(^|_)delete(_|$)"),
    re.compile(r"(^|_)remove(_|$)"),
    re.compile(r"(^|_)trash(_|$)"),
    re.compile(r"(^|_)create_event($|_)"),
    re.compile(r"(^|_)update_event($|_)"),
    re.compile(r"(^|_)patch_event($|_)"),
    re.compile(r"(^|_)post_message($|_)"),
)

# Explicitly autonomous actions (takes precedence if safe)
_AUTONOMOUS_EXCEPTIONS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|_)draft($|_)"),
    re.compile(r"(^|_)label($|_)"),
)


def requires_approval(tool_name: str) -> bool:
    """Return True if executing this tool requires Human-in-the-Loop confirmation."""
    normalized = tool_name.lower().replace("-", "_")
    if any(pattern.search(normalized) for pattern in _AUTONOMOUS_EXCEPTIONS):
        return False
    return any(pattern.search(normalized) for pattern in _GATED_TOOL_PATTERNS)


def wrap_tool_with_hitl(tool: BaseTool) -> BaseTool:
    """Wrap a critical tool with a LangGraph interrupt() gate while preserving its schema."""
    if not requires_approval(tool.name):
        return tool

    async def _gated_arun(**kwargs: Any) -> Any:
        decision = interrupt(
            {
                "type": "tool_approval",
                "tool": tool.name,
                "args": kwargs,
                "message": f"Validation requise avant d'exécuter `{tool.name}`.",
            }
        )
        if not isinstance(decision, dict) or not decision.get("approved", False):
            reason = (
                decision.get("reason", "Action refusée par l'utilisateur.")
                if isinstance(decision, dict)
                else "Action refusée par l'utilisateur."
            )
            return f"ACTION_CANCELLED: {reason}"
        return await tool.ainvoke(kwargs)

    def _gated_run(**kwargs: Any) -> Any:
        decision = interrupt(
            {
                "type": "tool_approval",
                "tool": tool.name,
                "args": kwargs,
                "message": f"Validation requise avant d'exécuter `{tool.name}`.",
            }
        )
        if not isinstance(decision, dict) or not decision.get("approved", False):
            reason = (
                decision.get("reason", "Action refusée par l'utilisateur.")
                if isinstance(decision, dict)
                else "Action refusée par l'utilisateur."
            )
            return f"ACTION_CANCELLED: {reason}"
        return tool.invoke(kwargs)

    return StructuredTool.from_function(
        func=_gated_run,
        coroutine=_gated_arun,
        name=tool.name,
        description=f"{tool.description} [HITL: requiert validation utilisateur]",
        args_schema=tool.args_schema,
    )


def apply_hitl_policy(tools: list[BaseTool]) -> list[BaseTool]:
    """Apply HITL gating across a list of tools."""
    return [wrap_tool_with_hitl(t) for t in tools]
