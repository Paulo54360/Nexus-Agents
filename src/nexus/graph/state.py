"""Shared state schema for the Nexus LangGraph supervisor graph."""

from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

WorkerName = Literal["gmail_agent", "productivity_agent", "asso_agent", "FINISH"]


class NexusState(TypedDict):
    """Global conversation & orchestration state persisted by LangGraph checkpointer."""

    messages: Annotated[list[AnyMessage], add_messages]
    next_agent: WorkerName
    step_count: int
