"""Assemble and compile the Nexus LangGraph supervisor graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from nexus.graph.agents.asso_agent import build_asso_agent
from nexus.graph.agents.gmail_agent import build_gmail_agent
from nexus.graph.agents.productivity_agent import build_productivity_agent
from nexus.graph.state import NexusState
from nexus.graph.supervisor import supervisor_node


def _route_from_supervisor(state: NexusState) -> str:
    next_agent = state.get("next_agent", "FINISH")
    if next_agent == "FINISH":
        return END
    return next_agent


def build_nexus_graph(
    tools_by_domain: dict[str, list[BaseTool]],
    checkpointer: BaseCheckpointSaver | None = None,
    get_discord_bot: Callable[[], Any] | None = None,
):
    """Compile the multi-agent Supervisor graph with persistent checkpointing."""
    gmail_subgraph = build_gmail_agent(tools_by_domain.get("gmail", []))
    productivity_subgraph = build_productivity_agent(tools_by_domain.get("productivity", []))
    asso_subgraph = build_asso_agent(get_discord_bot or (lambda: None))

    workflow = StateGraph(NexusState)
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("gmail_agent", gmail_subgraph)
    workflow.add_node("productivity_agent", productivity_subgraph)
    workflow.add_node("asso_agent", asso_subgraph)

    workflow.add_edge(START, "supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        {
            "gmail_agent": "gmail_agent",
            "productivity_agent": "productivity_agent",
            "asso_agent": "asso_agent",
            END: END,
        },
    )
    workflow.add_edge("gmail_agent", "supervisor")
    workflow.add_edge("productivity_agent", "supervisor")
    workflow.add_edge("asso_agent", "supervisor")

    return workflow.compile(checkpointer=checkpointer or MemorySaver())
