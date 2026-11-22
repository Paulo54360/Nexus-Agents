"""Association Discord specialist agent — strict read-only monitoring (Text + Forum channels)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from nexus.config import get_settings
from nexus.graph.memory import trim_conversation
from nexus.graph.supervisor import format_current_datetime
from nexus.llm import get_llm

logger = logging.getLogger(__name__)


def _parse_watch_channel_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        cleaned = part.strip()
        if cleaned.isdigit():
            ids.add(int(cleaned))
    return ids


def _can_read(channel: discord.abc.GuildChannel, me: discord.Member | None) -> bool:
    if me is None:
        return True
    perms = channel.permissions_for(me)
    return bool(perms.view_channel and perms.read_message_history)


def _get_allowed_channels(
    bot: discord.Client,
) -> tuple[list[discord.TextChannel], list[discord.ForumChannel]]:
    """Return readable TextChannels and ForumChannels on the configured association server."""
    settings = get_settings()
    if not settings.discord_asso_guild_id:
        return [], []
    guild = bot.get_guild(settings.discord_asso_guild_id)
    if guild is None:
        return [], []

    watch_ids = _parse_watch_channel_ids(settings.discord_asso_watch_channel_ids)
    me = guild.me

    text_channels = [
        ch
        for ch in guild.text_channels
        if (not watch_ids or ch.id in watch_ids) and _can_read(ch, me)
    ]
    forum_channels = [
        ch for ch in guild.forums if (not watch_ids or ch.id in watch_ids) and _can_read(ch, me)
    ]
    return text_channels, forum_channels


class _ReadMessagesInput(BaseModel):
    channel_id: str = Field(
        default="",
        description=(
            "ID numérique d'un salon texte précis à lire. Laisse vide pour lire les salons "
            "les plus récemment actifs du serveur de l'association."
        ),
    )
    hours: int = Field(
        default=24,
        ge=1,
        le=720,
        description="Fenêtre de temps en heures à remonter (par défaut 24h, max 720h = 30 jours).",
    )
    limit_per_channel: int = Field(
        default=40,
        ge=5,
        le=100,
        description="Nombre maximum de messages à lire par salon.",
    )


class _ReadForumInput(BaseModel):
    forum_id: str = Field(
        description="ID numérique du salon Forum Discord (récupéré via `discord_asso_list_channels`)."
    )
    include_archived: bool = Field(
        default=True,
        description="Inclure aussi les 'Anciens posts' archivés du forum (recommandé).",
    )
    max_posts: int = Field(
        default=25,
        ge=1,
        le=50,
        description="Nombre maximum de posts (fils) à récupérer dans le forum.",
    )
    messages_per_post: int = Field(
        default=8,
        ge=1,
        le=25,
        description="Nombre de messages à lire par post (premier message + derniers échanges).",
    )


def create_asso_discord_tools(get_bot: Callable[[], discord.Client | None]) -> list[BaseTool]:
    """Build strictly read-only Discord tools (Text + Forum channels) for the association server."""

    async def _list_channels() -> str:
        bot = get_bot()
        if bot is None or not bot.is_ready():
            return "Bot Discord non connecté."
        settings = get_settings()
        if not settings.discord_asso_guild_id:
            return (
                "DISCORD_ASSO_GUILD_ID n'est pas encore configuré dans .env. "
                "Demande à l'utilisateur d'ajouter l'ID du serveur de son association."
            )
        text_channels, forum_channels = _get_allowed_channels(bot)
        if not text_channels and not forum_channels:
            return (
                "Aucun salon lisible trouvé sur le serveur de l'association "
                "(vérifie que le bot a bien accès aux salons avec 'View Channels' + 'Read Message History')."
            )
        lines: list[str] = []
        if forum_channels:
            lines.append("## Salons Forum (utiliser `discord_asso_read_forum_posts`)")
            for ch in forum_channels:
                lines.append(f"- [Forum] #{ch.name} (ID: {ch.id})")
        if text_channels:
            lines.append("## Salons Texte (utiliser `discord_asso_read_messages`)")
            for ch in text_channels:
                lines.append(f"- [Texte] #{ch.name} (ID: {ch.id})")
        return "\n".join(lines)

    async def _read_forum_posts(
        forum_id: str,
        include_archived: bool = True,
        max_posts: int = 25,
        messages_per_post: int = 8,
    ) -> str:
        bot = get_bot()
        if bot is None or not bot.is_ready():
            return "Bot Discord non connecté."
        _, forum_channels = _get_allowed_channels(bot)
        if not forum_id.strip().isdigit():
            return f"forum_id invalide : '{forum_id}'."

        target_id = int(forum_id.strip())
        forum = next((f for f in forum_channels if f.id == target_id), None)
        if forum is None:
            return f"Salon Forum {forum_id} introuvable ou non autorisé."

        threads: dict[int, discord.Thread] = {t.id: t for t in forum.threads}
        if include_archived and len(threads) < max_posts:
            try:
                async for archived in forum.archived_threads(limit=max_posts):
                    threads.setdefault(archived.id, archived)
                    if len(threads) >= max_posts:
                        break
            except Exception as exc:
                logger.warning("Failed reading archived threads in #%s: %s", forum.name, exc)

        ordered = sorted(
            threads.values(),
            key=lambda t: t.last_message_id or t.id,
            reverse=True,
        )[:max_posts]

        if not ordered:
            return f"Aucun post trouvé dans le forum #{forum.name}."

        sections: list[str] = []
        for thread in ordered:
            tag_names = ", ".join(tag.name for tag in getattr(thread, "applied_tags", []))
            status = "archivé" if thread.archived else "actif"
            header = (
                f"### Post : {thread.name} ({status}"
                + (f", tags: {tag_names}" if tag_names else "")
                + ")"
            )

            lines: list[str] = []
            try:
                # Fetch first message (context of the dossier) + most recent messages
                first_msgs: list[discord.Message] = []
                async for m in thread.history(limit=2, oldest_first=True):
                    first_msgs.append(m)

                recent_msgs: list[discord.Message] = []
                if messages_per_post > 2:
                    async for m in thread.history(limit=messages_per_post - 2, oldest_first=False):
                        recent_msgs.append(m)
                    recent_msgs.reverse()

                seen_ids: set[int] = set()
                for m in [*first_msgs, *recent_msgs]:
                    if m.id in seen_ids:
                        continue
                    seen_ids.add(m.id)
                    content = (m.clean_content or "").strip()
                    if not content:
                        continue
                    ts = m.created_at.strftime("%d/%m/%Y %H:%M")
                    lines.append(f"  - [{ts}] {m.author.display_name}: {content[:400]}")
            except Exception as exc:
                logger.warning("Failed reading thread '%s': %s", thread.name, exc)
                lines.append(f"  - (impossible de lire les messages : {exc})")

            sections.append(
                header + "\n" + ("\n".join(lines) if lines else "  - (aucun message texte)")
            )

        output = f"Posts du Forum #{forum.name} ({len(ordered)} posts lus) :\n\n" + "\n\n".join(
            sections
        )
        return output[:24000]

    async def _read_messages(
        channel_id: str = "",
        hours: int = 24,
        limit_per_channel: int = 40,
    ) -> str:
        bot = get_bot()
        if bot is None or not bot.is_ready():
            return "Bot Discord non connecté."
        settings = get_settings()
        if not settings.discord_asso_guild_id:
            return (
                "DISCORD_ASSO_GUILD_ID n'est pas encore configuré dans .env. "
                "Ajoute l'ID du serveur de l'association et redémarre Nexus."
            )

        text_channels, forum_channels = _get_allowed_channels(bot)

        # If caller accidentally passed a Forum ID to read_messages, seamlessly delegate to forum reader
        if channel_id.strip().isdigit():
            target_id = int(channel_id.strip())
            if any(f.id == target_id for f in forum_channels):
                return await _read_forum_posts(forum_id=channel_id)
            text_channels = [ch for ch in text_channels if ch.id == target_id]
            if not text_channels:
                return f"Salon {channel_id} introuvable ou non autorisé sur le serveur de l'association."

        if not text_channels:
            return "Aucun salon texte lisible sur le serveur de l'association."

        text_channels.sort(key=lambda ch: ch.last_message_id or 0, reverse=True)

        since = datetime.now(UTC) - timedelta(hours=hours)
        sections: list[str] = []
        total_msgs = 0

        for ch in text_channels[:25]:
            collected: list[str] = []
            try:
                async for msg in ch.history(
                    after=since, limit=limit_per_channel, oldest_first=True
                ):
                    content = (msg.clean_content or "").strip()
                    if not content and not msg.attachments:
                        continue
                    ts = msg.created_at.strftime("%d/%m %H:%M")
                    author = msg.author.display_name
                    attach_note = (
                        f" [+{len(msg.attachments)} pièce(s) jointe(s)]" if msg.attachments else ""
                    )
                    collected.append(f"[{ts}] {author}: {content}{attach_note}")
            except discord.Forbidden:
                logger.warning("Missing read permission on association channel #%s", ch.name)
                continue
            except Exception as exc:
                logger.warning("Failed reading channel #%s: %s", ch.name, exc)
                continue

            if collected:
                total_msgs += len(collected)
                sections.append(f"## Salon #{ch.name}\n" + "\n".join(collected))

        if not sections:
            return f"Aucun nouveau message sur les salons texte au cours des dernières {hours}h."

        header = f"Activité du serveur de l'association ({total_msgs} messages sur les dernières {hours}h) :\n\n"
        return (header + "\n\n".join(sections))[:18000]

    return [
        StructuredTool.from_function(
            coroutine=_list_channels,
            name="discord_asso_list_channels",
            description=(
                "Liste tous les salons Texte ET les salons Forum accessibles en lecture seule "
                "sur le serveur Discord de l'association."
            ),
        ),
        StructuredTool.from_function(
            coroutine=_read_forum_posts,
            name="discord_asso_read_forum_posts",
            description=(
                "Lit tous les posts (actifs et 'Anciens posts' archivés) d'un salon Forum Discord "
                "(ex. forum 'suivi-de-modération'), avec le titre de chaque post et son contexte."
            ),
            args_schema=_ReadForumInput,
        ),
        StructuredTool.from_function(
            coroutine=_read_messages,
            name="discord_asso_read_messages",
            description=(
                "Lit les messages récents (en lecture seule) sur les salons texte du serveur Discord "
                "de l'association pour résumer l'activité, les décisions et les actions à faire."
            ),
            args_schema=_ReadMessagesInput,
        ),
    ]


def _asso_prompt(state: dict) -> list:
    system = SystemMessage(
        content=(
            f"Tu es l'Agent Veille Association de Nexus. Date et heure actuelles : {format_current_datetime()}.\n"
            "Tes responsabilités (strictement en LECTURE SEULE sur le serveur Discord de l'association) :\n"
            "1. Appelle TOUJOURS `discord_asso_list_channels` d'abord pour identifier les bons salons "
            "(Texte ET Forums).\n"
            "2. Si le salon demandé est un **Forum** (ex. `suivi-de-modération`), utilise "
            "`discord_asso_read_forum_posts` avec `include_archived=True` pour lire TOUS les posts.\n"
            "3. **DISTINCTION CRITIQUE** : Dans un salon/forum de modération, les personnes faisant l'objet "
            "d'un suivi sont les **sujets des posts/dossiers** (ex. le titre du post : 'Daten', 'yuri', 'Teito', "
            "'Brasko', 'Yannis', etc.) — NE confonds JAMAIS les **modérateurs/staff qui rédigent les messages** "
            "(ex. Paulo, Adra, Horus, Twifus, Hiroty, Taiga...) avec les personnes suivies ! Ignore aussi les "
            "posts généraux de règlement (ex. 'Les anciens ban de dionysos') quand on demande une fiche par personne.\n"
            "4. Tu ne postes JAMAIS rien sur le serveur de l'association.\n"
            "5. Fournis uniquement un récapitulatif structuré personne par personne (nom/pseudo + résumé factuel "
            "du dossier) SANS JAMAIS dire que tu n'as pas accès à Notion/Calendar : le Superviseur passera "
            "automatiquement le relais à `productivity_agent` pour créer/mettre à jour les fiches Notion."
        )
    )
    return [system, *trim_conversation(state["messages"])]


def build_asso_agent(get_bot: Callable[[], Any]):
    """Build the association Discord monitoring ReAct subgraph."""
    tools = create_asso_discord_tools(get_bot)
    llm = get_llm(tier="smart", temperature=0.1)
    return create_react_agent(
        model=llm,
        tools=tools,
        prompt=_asso_prompt,
        name="asso_agent",
    )
