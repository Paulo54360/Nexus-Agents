"""APScheduler jobs driving Nexus's proactive daily workflows."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from nexus.config import get_settings
from nexus.interfaces.discord_bot import NexusDiscordBot
from nexus.runtime import run_turn

logger = logging.getLogger(__name__)


def build_scheduler(graph: Any, discord_bot: NexusDiscordBot | None) -> AsyncIOScheduler:
    """Create and configure proactive jobs posting into dedicated Discord channels."""
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.timezone)

    async def morning_briefing_job() -> None:
        thread_id = f"briefing-{datetime.now().strftime('%Y%m%d')}"
        prompt = (
            "Prépare mon briefing matinal concis : "
            "1) Résume les emails non lus importants, "
            "2) Liste mes événements Google Calendar d'aujourd'hui, "
            "3) Rappelle mes tâches Notion prioritaires."
        )
        logger.info("Running proactive morning briefing (%s)", thread_id)
        result = await run_turn(
            graph, thread_id=thread_id, user_message=prompt, user_id="scheduler"
        )
        if discord_bot and discord_bot.is_ready():
            await discord_bot.post_proactive_result(settings.discord_briefing_channel_id, result)

    async def gmail_triage_job() -> None:
        thread_id = f"gmail-triage-{datetime.now().strftime('%Y%m%d-%H%M')}"
        prompt = (
            "Vérifie mes derniers emails non lus sur Gmail. "
            "Applique des labels pertinents (Urgent, Entretien, Asso, Newsletter), "
            "crée un brouillon de réponse si un email important attend un retour, "
            "et fais-moi un court récapitulatif sans rien envoyer."
        )
        logger.info("Running proactive Gmail triage (%s)", thread_id)
        result = await run_turn(
            graph, thread_id=thread_id, user_message=prompt, user_id="scheduler"
        )
        if discord_bot and discord_bot.is_ready():
            await discord_bot.post_proactive_result(
                settings.discord_gmail_triage_channel_id, result
            )

    async def asso_digest_job() -> None:
        if not settings.discord_asso_guild_id:
            return
        thread_id = f"asso-digest-{datetime.now().strftime('%Y%m%d')}"
        prompt = (
            "Lis l'activité des dernières 24h sur le serveur Discord de mon association "
            "et rédige un digest clair : décisions importantes, événements à venir, "
            "et actions ou tâches qui me concernent."
        )
        logger.info("Running proactive association Discord digest (%s)", thread_id)
        result = await run_turn(
            graph, thread_id=thread_id, user_message=prompt, user_id="scheduler"
        )
        if discord_bot and discord_bot.is_ready():
            await discord_bot.post_proactive_result(settings.discord_asso_digest_channel_id, result)

    scheduler.add_job(
        morning_briefing_job,
        trigger=CronTrigger(hour=settings.briefing_hour, minute=settings.briefing_minute),
        id="morning_briefing",
        replace_existing=True,
    )
    scheduler.add_job(
        gmail_triage_job,
        trigger=IntervalTrigger(minutes=settings.gmail_triage_interval_minutes),
        id="gmail_triage",
        replace_existing=True,
    )
    scheduler.add_job(
        asso_digest_job,
        trigger=CronTrigger(hour=settings.asso_digest_hour, minute=settings.asso_digest_minute),
        id="asso_digest",
        replace_existing=True,
    )
    return scheduler
