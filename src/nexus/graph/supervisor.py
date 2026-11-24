"""Supervisor node routing requests between specialist agents and final synthesis."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import AIMessage, SystemMessage
from pydantic import BaseModel, Field

from nexus.config import get_settings
from nexus.graph.memory import trim_conversation
from nexus.graph.state import NexusState
from nexus.llm import get_llm

logger = logging.getLogger(__name__)

MAX_SUPERVISOR_STEPS = 6

_WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")


def format_current_datetime() -> str:
    """Return a locale-independent French date/time string for agent prompts."""
    tz_name = get_settings().timezone
    try:
        now = datetime.now(ZoneInfo(tz_name))
    except ZoneInfoNotFoundError:
        now = datetime.now(UTC)
        tz_name = "UTC"
    weekday = _WEEKDAYS_FR[now.weekday()]
    return f"{weekday} {now.strftime('%Y-%m-%d %H:%M')} ({tz_name})"


def _build_router_prompt() -> str:
    return f"""Tu es le routeur du Superviseur Nexus. Date et heure actuelles : {format_current_datetime()}.

Agents spécialisés disponibles :
- `gmail_agent` : Gmail (lecture, résumé, tri, labels, brouillons, envoi).
- `productivity_agent` : Google Calendar (agenda, événements) et Notion (tâches, bases, fiches LPA).
- `asso_agent` : serveur Discord du staff / association (salons texte, forums, suivi de modération).

Règles STRICTES :
1. Délègue au bon agent dès qu'une information externe ou action est nécessaire.
2. Pour une demande mixte (ex. lire le Discord asso PUIS écrire dans Notion), appelle d'abord `asso_agent`, puis `productivity_agent`, puis `FINISH`.
3. ANTI-BOUCLE : si un agent vient déjà de répondre avec le résultat ou signale un blocage/permission manquante, choisis `FINISH` (ne le rappelle pas en boucle).
4. Choisis `FINISH` dès que toutes les infos nécessaires sont dans la conversation.
"""


def _build_responder_prompt() -> str:
    return f"""Tu es Nexus, l'assistant personnel multi-agents. Date et heure actuelles : {format_current_datetime()}.
Rédige la réponse finale en français à partir des résultats déjà collectés par tes agents ci-dessus, avec une **mise en forme Markdown propre, hiérarchisée et aérée** :
- Commence par un titre principal `## ` clair avec un emoji discret (ex. `## 🏛️ Digest Discord — Association`, `## 📋 Tes tâches Notion`, `## 📬 Tes mails`, `## 📅 Ton agenda`).
- Utilise `### ` pour les sous-sections (ex. `### #moderateur`, `### Points d'action`) — n'utilise PAS `####` et n'empile PAS de lignes `---` inutiles entre chaque section.
- Utilise des listes à puces simples (`- `) sans mettre d'emoji-puce redondant après le tiret (évite `- 🔹 ...`, préfère `- **Sujet** : ...`).
- Mets en **gras** les éléments importants (noms, horaires, dates, décisions).
- Termine si pertinent par une courte suggestion en citation (`> 💡 ...`).
- Reste concis, factuel et lisible sur desktop comme sur mobile.
"""


class RouteDecision(BaseModel):
    next_agent: Literal["gmail_agent", "productivity_agent", "asso_agent", "FINISH"] = Field(
        description="Prochain agent à invoquer, ou FINISH si toutes les infos sont prêtes."
    )
    reasoning: str = Field(
        description="Justification très courte (1 phrase max) du choix de routage."
    )


async def _decide_route(messages: list) -> RouteDecision:
    """Ask the fast router (with smart fallback) for a compact routing decision."""
    prompt_msgs = [SystemMessage(content=_build_router_prompt()), *messages]
    for tier in ("fast", "smart"):
        try:
            llm = get_llm(tier=tier, temperature=0.0).with_structured_output(RouteDecision)
            return await llm.ainvoke(prompt_msgs)
        except Exception as exc:
            logger.warning("Router structured output failed on tier '%s': %s", tier, exc)
    # Last-resort safe fallback
    return RouteDecision(
        next_agent="FINISH", reasoning="Fallback après erreur de routage structuré."
    )


async def supervisor_node(state: NexusState) -> dict:
    """Decide whether to delegate to a specialist agent or synthesize the final Discord response."""
    step_count = state.get("step_count", 0)
    if step_count >= MAX_SUPERVISOR_STEPS:
        logger.warning("Supervisor reached MAX_SUPERVISOR_STEPS (%d), forcing FINISH.", step_count)
        return {
            "next_agent": "FINISH",
            "step_count": step_count,
            "messages": [
                AIMessage(
                    content=(
                        "J'ai atteint la limite d'étapes d'orchestration pour cette demande. "
                        "Voici ce que j'ai déjà rassemblé ci-dessus — précise si tu veux que je continue."
                    )
                )
            ],
        }

    trimmed = trim_conversation(state["messages"])
    decision = await _decide_route(trimmed)
    logger.info("Supervisor routed to %s (%s)", decision.next_agent, decision.reasoning)

    update: dict = {
        "next_agent": decision.next_agent,
        "step_count": step_count + 1,
    }
    if decision.next_agent == "FINISH":
        # Generate rich Markdown freely outside JSON so open-source models never truncate JSON
        responder = get_llm(tier="smart", temperature=0.2)
        final_msg = await responder.ainvoke(
            [SystemMessage(content=_build_responder_prompt()), *trimmed]
        )
        content = (
            final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
        )
        update["messages"] = [AIMessage(content=content)]
    return update
