"""Gmail specialist agent — autonomous triage/labels/drafts, HITL-gated sends/deletes."""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from nexus.graph.hitl import apply_hitl_policy
from nexus.graph.memory import trim_conversation
from nexus.graph.supervisor import format_current_datetime
from nexus.llm import get_llm


def _gmail_prompt(state: dict) -> list:
    system = SystemMessage(
        content=(
            f"Tu es l'Agent Gmail de Nexus. Date et heure actuelles : {format_current_datetime()}.\n"
            "Tes responsabilités (domaine Gmail uniquement) :\n"
            "- NE RECYCLE JAMAIS d'anciens emails de l'historique : appelle TOUJOURS les outils MCP Gmail en temps réel.\n"
            "- Lire, résumer et prioriser les emails importants.\n"
            "- Appliquer des labels et rédiger des brouillons de réponse de manière autonome.\n"
            "- Si l'utilisateur demande explicitement d'envoyer un email ou de supprimer un message, "
            "appelle l'outil dédié (`gmail_send_email` / `gmail_delete_email`) : le système demandera "
            "automatiquement validation sur Discord.\n"
            "- Tu ne gères QUE Gmail : si la demande contient aussi une partie Google Calendar ou Notion, "
            "traite uniquement la partie Gmail (le Superviseur confiera le reste à `productivity_agent`).\n"
            "- Réponds en français de façon claire et concise."
        )
    )
    return [system, *trim_conversation(state["messages"])]


def build_gmail_agent(tools: list[BaseTool]):
    """Build the Gmail ReAct subgraph with HITL protection applied to critical tools."""
    protected_tools = apply_hitl_policy(tools)
    llm = get_llm(tier="smart", temperature=0.2)
    return create_react_agent(
        model=llm,
        tools=protected_tools,
        prompt=_gmail_prompt,
        name="gmail_agent",
    )
