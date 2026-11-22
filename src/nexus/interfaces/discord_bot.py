"""Discord Bot interface for #command-center chat, HITL approval buttons, and proactive feeds."""

from __future__ import annotations

import json
import logging
from typing import Any

import discord

from nexus.config import get_settings
from nexus.runtime import TurnResult, resume_turn, run_turn

logger = logging.getLogger(__name__)


def _format_approval_embed(pending: dict[str, Any], thread_id: str) -> discord.Embed:
    tool_name = pending.get("tool", "action_inconnue")
    args_pretty = json.dumps(pending.get("args", {}), indent=2, ensure_ascii=False)
    embed = discord.Embed(
        title="Validation requise (Human-in-the-Loop)",
        description=pending.get("message", f"L'agent souhaite exécuter `{tool_name}`."),
        color=discord.Color.orange(),
    )
    embed.add_field(name="Outil", value=f"`{tool_name}`", inline=True)
    embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=True)
    embed.add_field(name="Paramètres", value=f"```json\n{args_pretty[:950]}\n```", inline=False)
    return embed


class ApprovalView(discord.ui.View):
    """Interactive ✅ Valider / ❌ Refuser Discord buttons resuming a LangGraph interrupt."""

    def __init__(self, graph: Any, thread_id: str, allowed_user_id: int | None):
        super().__init__(timeout=3600)
        self.graph = graph
        self.thread_id = thread_id
        self.allowed_user_id = allowed_user_id

    async def _check_authorized(self, interaction: discord.Interaction) -> bool:
        if self.allowed_user_id and interaction.user.id != self.allowed_user_id:
            await interaction.response.send_message(
                "Action réservée au propriétaire de Nexus.", ephemeral=True
            )
            return False
        return True

    async def _handle_decision(self, interaction: discord.Interaction, approved: bool) -> None:
        if not await self._check_authorized(interaction):
            return

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        status_label = (
            "✅ Validé — reprise en cours..." if approved else "❌ Refusé — annulation..."
        )
        await interaction.response.edit_message(content=status_label, view=self)

        result = await resume_turn(
            self.graph,
            thread_id=self.thread_id,
            approved=approved,
            user_id=str(interaction.user.id),
        )
        await _send_turn_result(interaction.channel, self.graph, result, self.allowed_user_id)

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._handle_decision(interaction, approved=True)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_button(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await self._handle_decision(interaction, approved=False)


async def _send_turn_result(
    channel: Any,
    graph: Any,
    result: TurnResult,
    allowed_user_id: int | None,
) -> None:
    if result.status == "approval_required" and result.pending_approval:
        embed = _format_approval_embed(result.pending_approval, result.thread_id)
        view = ApprovalView(
            graph=graph, thread_id=result.thread_id, allowed_user_id=allowed_user_id
        )
        await channel.send(embed=embed, view=view)
        return

    # Render clean, mobile-friendly Discord Embeds (up to 4096 chars per embed)
    text = result.reply.strip()
    chunks = [text[start : start + 3800] for start in range(0, len(text), 3800)] or ["✅ Terminé."]
    for idx, chunk in enumerate(chunks):
        embed = discord.Embed(
            description=chunk,
            color=discord.Color.from_rgb(56, 189, 248),  # Modern Sky/Cyan accent
        )
        if idx == len(chunks) - 1:
            embed.set_footer(text="Nexus Agents • LangGraph + MCP")
        await channel.send(embed=embed)


class NexusDiscordBot(discord.Client):
    """Outbound-only WebSocket Discord bot (zero open inbound ports required)."""

    def __init__(self, graph: Any, automation_engine: Any = None):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.graph = graph
        self.automation_engine = automation_engine
        self.settings = get_settings()
        self._channel_generations: dict[int, int] = {}

    async def on_ready(self) -> None:
        logger.info("Nexus Discord bot connected as %s", self.user)

    async def on_thread_create(self, thread: discord.Thread) -> None:
        if self.automation_engine:
            await self.automation_engine.handle_forum_post_created(thread)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        # Evaluate passive keyword automations on watched servers (never replies there)
        if self.automation_engine and message.guild:
            cmd_channel = self.settings.discord_command_center_channel_id
            if not cmd_channel or message.channel.id != cmd_channel:
                await self.automation_engine.handle_message_keyword(message)

        # Strict owner-only guard for #command-center commands
        allowed_uid = self.settings.discord_allowed_user_id
        if allowed_uid and message.author.id != allowed_uid:
            return

        # Listen in #command-center or direct messages
        cmd_channel = self.settings.discord_command_center_channel_id
        is_dm = isinstance(message.channel, discord.DMChannel)
        if cmd_channel and not is_dm and message.channel.id != cmd_channel:
            return

        stripped = message.content.strip()
        lower = stripped.lower()

        # Built-in slash-like quick commands
        if lower in {"!reset", "!clear", "/reset"}:
            gen = self._channel_generations.get(message.channel.id, 0) + 1
            self._channel_generations[message.channel.id] = gen
            await message.channel.send(
                "🧹 Mémoire de conversation réinitialisée — on repart à zéro !"
            )
            return

        if lower in {"!automations", "!auto"} and self.automation_engine:
            embed = discord.Embed(
                description=self.automation_engine.list_summary(),
                color=discord.Color.from_rgb(56, 189, 248),
            )
            embed.set_footer(text="Nexus Agents • Automation Engine")
            await message.channel.send(embed=embed)
            return

        if lower == "!reload" and self.automation_engine:
            rules = self.automation_engine.reload()
            active = sum(1 for r in rules if r.enabled)
            await message.channel.send(
                f"🔄 `config/automations.yaml` rechargé ({active}/{len(rules)} actives)."
            )
            return

        if lower.startswith("!run ") and self.automation_engine:
            rule_id = stripped.split(maxsplit=1)[1].strip()
            await message.channel.send(
                f"⚡ Lancement manuel de l'automatisation **`{rule_id}`**..."
            )
            async with message.channel.typing():
                ok = await self.automation_engine.trigger_by_id(
                    rule_id, notify_channel_id=message.channel.id
                )
            if not ok:
                await message.channel.send(
                    f"⚠️ Automatisation `{rule_id}` introuvable. Tape `!automations`."
                )
            return

        gen = self._channel_generations.get(message.channel.id, 0)
        thread_id = (
            f"discord-{message.channel.id}-v{gen}" if gen else f"discord-{message.channel.id}"
        )
        async with message.channel.typing():
            try:
                result = await run_turn(
                    self.graph,
                    thread_id=thread_id,
                    user_message=message.content,
                    user_id=str(message.author.id),
                )
                await _send_turn_result(message.channel, self.graph, result, allowed_uid)
            except Exception:
                logger.exception("Error handling Discord message on thread %s", thread_id)
                await message.channel.send(
                    "⚠️ Une erreur est survenue lors du traitement. Consulte les logs Nexus/Langfuse."
                )

    async def post_proactive_result(self, channel_id: int | None, result: TurnResult) -> None:
        """Deliver a scheduled agent output (and optional HITL buttons) to a dedicated channel."""
        if not channel_id:
            logger.info("Proactive channel unset; logging result: %s", result.reply[:200])
            return
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        await _send_turn_result(
            channel,
            self.graph,
            result,
            self.settings.discord_allowed_user_id,
        )
