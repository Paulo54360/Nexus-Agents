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


def _build_supervisor_prompt() -> str:
    return f"""Tu es le Superviseur de Nexus, un orchestrateur multi-agents personnel.
Date et heure actuelles : {format_current_datetime()}.

Tu supervises trois agents spécialisés :
- `gmail_agent` : tout ce qui concerne Gmail (lecture, résumé, tri, labels, brouillons, envoi).
- `productivity_agent` : Google Calendar (agenda, disponibilités, événements) et Notion (tâches, to-do, rappels).
- `asso_agent` : lecture seule et résumés du serveur Discord de l'association (salons, décisions, événements, actions à suivre).

Règles de routage STRICTES :
1. Décompose mentalement la demande de l'utilisateur en sous-tâches (Gmail vs Calendar/Notion vs Discord Association).
2. Ne choisis JAMAIS `FINISH` tant que TOUTES les parties de la demande n'ont pas été traitées.
3. Pour une demande mixte (ex. « résume ce qui s'est passé sur le Discord de l'asso ET ajoute les actions dans Notion » ou « lis mes mails ET ajoute l'événement au calendrier ») :
   - Délègue d'abord à l'agent qui lit la source (`asso_agent` ou `gmail_agent`),
   - Puis délègue à `productivity_agent` pour créer les tâches Notion ou événements Calendar,
   - Et seulement ensuite choisis `FINISH` avec une synthèse globale.
4. Si un agent indique ne pas posséder un outil d'un autre domaine, délègue immédiatement à l'agent compétent au lieu de conclure.
5. **ANTI-BOUCLE** : Si le MÊME agent vient déjà d'être appelé et indique qu'une ressource est introuvable, qu'il manque une permission (ex. base Notion non partagée) ou qu'une information manque, NE le rappelle PAS une deuxième fois : choisis immédiatement `FINISH` et explique clairement ce qui a été trouvé et ce qui bloque.
6. Quand tu choisis `FINISH`, rédige une réponse finale en français dans `final_response` avec un **style visuel Discord soigné et aéré** :
   - Commence par un titre clair avec un emoji (ex. `### 📋 Tes tâches Notion — ToDo`, `### 📬 Tes mails`, `### 📅 Ton agenda`, `### 🏛️ Digest Discord — Association`).
   - Utilise des **retours à la ligne** et des **listes à puces** (`- `) — JAMAIS une liste collée sur une seule ligne.
   - Mets en **gras** les titres, expéditeurs, dates ou horaires importants ; ajoute des badges discrets si pertinent (`🔴`, `🟡`, `🟢`, `✅`, `🕒`).
   - Termine si pertinent par une courte suggestion en citation (`> 💡 ...`).
   - Reste concis et lisible sur mobile.
"""


class RouteDecision(BaseModel):
    next_agent: Literal["gmail_agent", "productivity_agent", "asso_agent", "FINISH"] = Field(
        description="Prochain agent à invoquer, ou FINISH uniquement quand TOUTE la demande est traitée."
    )
    reasoning: str = Field(description="Brève justification du routage.")
    final_response: str | None = Field(
        default=None,
        description="Réponse finale en français adressée à l'utilisateur (obligatoire si FINISH).",
    )


async def supervisor_node(state: NexusState) -> dict:
    """Decide whether to delegate to a specialist agent or conclude with a final answer."""
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

    llm = get_llm(tier="fast", temperature=0.0).with_structured_output(RouteDecision)
    decision: RouteDecision = await llm.ainvoke(
        [SystemMessage(content=_build_supervisor_prompt()), *trim_conversation(state["messages"])]
    )

    logger.info("Supervisor routed to %s (%s)", decision.next_agent, decision.reasoning)

    update: dict = {
        "next_agent": decision.next_agent,
        "step_count": step_count + 1,
    }
    if decision.next_agent == "FINISH" and decision.final_response:
        update["messages"] = [AIMessage(content=decision.final_response)]
    return update
