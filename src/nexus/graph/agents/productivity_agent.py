"""Productivity specialist agent — Google Calendar + Notion tasks & reminders."""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import create_react_agent

from nexus.graph.hitl import apply_hitl_policy
from nexus.graph.memory import trim_conversation
from nexus.graph.supervisor import format_current_datetime
from nexus.llm import get_llm


def _productivity_prompt(state: dict) -> list:
    system = SystemMessage(
        content=(
            f"Tu es l'Agent Productivité (Google Calendar & Notion) de Nexus.\n"
            f"Date et heure actuelles : {format_current_datetime()}.\n"
            "RÈGLES STRICTES :\n"
            "1. NE RECYCLE JAMAIS des informations anciennes de l'historique : appelle TOUJOURS les vrais outils MCP.\n"
            "2. Pour Google Calendar : l'utilisateur possède PLUSIEURS agendas (principal + agendas secondaires "
            "comme 'Planning de couple', 'Dionysos Calendrier', etc.). Appelle TOUJOURS `list-calendars` d'abord "
            "pour récupérer tous ses agendas, puis interroge `list-events` sur l'ensemble des agendas pertinents "
            "(en utilisant la vraie date actuelle pour calculer `timeMin` / `timeMax`, ex. les 7 prochains jours).\n"
            "3. Pour chaque événement trouvé, indique TOUJOURS le **jour et la date exacte** (ex. Mardi 24 novembre), "
            "l'horaire, le titre et le nom de l'agenda.\n"
            "4. Pour Notion : interroge directement la base de données / les pages autorisées via les outils MCP. "
            "EXHAUSTIVITÉ OBLIGATOIRE : si l'utilisateur demande de créer ou mettre à jour N fiches, "
            "traite TOUS les éléments jusqu'au dernier (en appelant les outils en parallèle si possible) "
            "sans jamais t'arrêter à la moitié ; s'il reste des éléments non traités, liste-les explicitement.\n"
            "5. Pour créer ou modifier un événement Google Calendar, appelle l'outil dédié : le système demandera "
            "automatiquement validation sur Discord.\n"
            "6. Tu ne gères QUE Calendar et Notion : si la demande contient aussi une partie Gmail, "
            "traite uniquement Calendar/Notion (le Superviseur confiera Gmail à `gmail_agent`)."
        )
    )
    return [system, *trim_conversation(state["messages"])]


def build_productivity_agent(tools: list[BaseTool]):
    """Build the Calendar + Notion ReAct subgraph with HITL protection."""
    protected_tools = apply_hitl_policy(tools)
    llm = get_llm(tier="smart", temperature=0.1)
    return create_react_agent(
        model=llm,
        tools=protected_tools,
        prompt=_productivity_prompt,
        name="productivity_agent",
    )
