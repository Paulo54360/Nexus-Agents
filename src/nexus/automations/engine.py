"""Load and execute declarative automations from config/automations.yaml."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import discord
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from nexus.runtime import run_turn

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _parse_optional_int(raw: Any) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return int(text) if text.isdigit() else None


@dataclass
class AutomationRule:
    id: str
    name: str
    enabled: bool
    trigger: dict[str, Any]
    prompt: str
    notify_channel_id: int | None
    fallback_notify_channel_id: int | None = None

    @property
    def target_channel_id(self) -> int | None:
        return self.notify_channel_id or self.fallback_notify_channel_id


class AutomationEngine:
    """Executes event-driven (Discord forums/messages) and custom CRON rules."""

    def __init__(self, graph: Any, config_path: Path = Path("config/automations.yaml")):
        self.graph = graph
        self.config_path = config_path
        self.rules: list[AutomationRule] = []
        self._bot: Any = None
        self.reload()

    def attach_bot(self, bot: Any) -> None:
        self._bot = bot

    def reload(self) -> list[AutomationRule]:
        """Load automation rules from YAML with environment variable substitution."""
        if not self.config_path.exists():
            logger.info("No automations config found at %s.", self.config_path)
            self.rules = []
            return self.rules

        raw = _expand_env(yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {})
        parsed: list[AutomationRule] = []
        for entry in raw.get("automations", []):
            parsed.append(
                AutomationRule(
                    id=str(entry["id"]),
                    name=str(entry.get("name", entry["id"])),
                    enabled=bool(entry.get("enabled", True)),
                    trigger=dict(entry.get("trigger", {})),
                    prompt=str(entry.get("prompt", "")),
                    notify_channel_id=_parse_optional_int(entry.get("notify_channel_id")),
                    fallback_notify_channel_id=_parse_optional_int(
                        entry.get("fallback_notify_channel_id")
                    ),
                )
            )
        self.rules = parsed
        active_count = sum(1 for r in self.rules if r.enabled)
        logger.info("Loaded %d automations (%d enabled).", len(self.rules), active_count)
        return self.rules

    def list_summary(self) -> str:
        """Format a Discord-friendly summary of configured automations."""
        if not self.rules:
            return "### ⚙️ Automatisations\nAucune automatisation configurée dans `config/automations.yaml`."
        lines = ["### ⚙️ Automatisations Nexus"]
        for rule in self.rules:
            badge = "🟢" if rule.enabled else "⚪"
            trig_type = rule.trigger.get("type", "inconnu")
            lines.append(f"- {badge} **`{rule.id}`** — {rule.name} *(trigger: `{trig_type}`)*")
        lines.append("\n> 💡 Tape `!run <id>` pour lancer une automatisation manuellement.")
        return "\n".join(lines)

    def list_rules_data(self) -> list[dict[str, Any]]:
        """Return JSON-serializable rule definitions for the Mission Control UI."""
        return [
            {
                "id": r.id,
                "name": r.name,
                "enabled": r.enabled,
                "trigger": r.trigger,
                "prompt": r.prompt.strip(),
                "notify_channel_id": r.target_channel_id,
            }
            for r in self.rules
        ]

    def toggle_rule(self, rule_id: str) -> dict[str, Any] | None:
        """Toggle an automation rule's enabled flag in memory."""
        rule = next((r for r in self.rules if r.id == rule_id), None)
        if rule is None:
            return None
        rule.enabled = not rule.enabled
        logger.info("Automation '%s' toggled -> enabled=%s", rule.id, rule.enabled)
        return {
            "id": rule.id,
            "name": rule.name,
            "enabled": rule.enabled,
            "trigger": rule.trigger,
            "prompt": rule.prompt.strip(),
        }

    def register_cron_jobs(self, scheduler: AsyncIOScheduler) -> None:
        """Register all enabled `cron` rules from automations.yaml into APScheduler."""
        for rule in self.rules:
            if not rule.enabled or rule.trigger.get("type") != "cron":
                continue
            cron_kwargs = {
                k: v
                for k, v in rule.trigger.items()
                if k in {"year", "month", "day", "week", "day_of_week", "hour", "minute", "second"}
            }
            if not cron_kwargs:
                logger.warning("Cron automation '%s' has no schedule fields; skipping.", rule.id)
                continue

            async def _job(r: AutomationRule = rule) -> None:
                await self.execute_rule(r, context={})

            scheduler.add_job(
                _job,
                trigger=CronTrigger(**cron_kwargs),
                id=f"auto-{rule.id}",
                replace_existing=True,
            )
            logger.info("Scheduled YAML cron automation '%s' (%s).", rule.id, cron_kwargs)

    async def execute_rule(
        self,
        rule: AutomationRule,
        context: dict[str, str],
        override_channel_id: int | None = None,
    ) -> None:
        """Render the rule's prompt, run it through LangGraph, and post the result to Discord."""

        class _SafeDict(dict):
            def __missing__(self, key: str) -> str:
                return f"{{{key}}}"

        prompt = rule.prompt.format_map(_SafeDict(context))
        thread_id = f"auto-{rule.id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        logger.info("Executing automation '%s' (thread=%s)", rule.id, thread_id)
        try:
            result = await run_turn(
                self.graph,
                thread_id=thread_id,
                user_message=prompt,
                user_id=f"automation:{rule.id}",
            )
            channel_id = override_channel_id or rule.target_channel_id
            if self._bot and self._bot.is_ready() and channel_id:
                await self._bot.post_proactive_result(channel_id, result)
            else:
                logger.info("Automation '%s' completed: %s", rule.id, result.reply[:200])
        except Exception:
            logger.exception("Automation '%s' failed.", rule.id)

    async def trigger_by_id(self, rule_id: str, notify_channel_id: int | None = None) -> bool:
        """Manually trigger an automation rule by ID (via !run <id>)."""
        rule = next((r for r in self.rules if r.id == rule_id), None)
        if rule is None:
            return False
        await self.execute_rule(rule, context={}, override_channel_id=notify_channel_id)
        return True

    async def handle_forum_post_created(self, thread: discord.Thread) -> None:
        """Evaluate `discord_forum_post_created` rules whenever a new Discord Forum post opens."""
        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            return

        matching: list[AutomationRule] = []
        for rule in self.rules:
            if not rule.enabled or rule.trigger.get("type") != "discord_forum_post_created":
                continue
            expected_guild = _parse_optional_int(rule.trigger.get("guild_id"))
            if expected_guild and thread.guild.id != expected_guild:
                continue
            expected_forum_id = _parse_optional_int(rule.trigger.get("forum_id"))
            if expected_forum_id and parent.id != expected_forum_id:
                continue
            name_filter = str(rule.trigger.get("forum_name_contains", "")).strip().lower()
            if name_filter and name_filter not in parent.name.lower():
                continue
            matching.append(rule)

        if not matching:
            return

        # Wait briefly so Discord finishes indexing the forum post's starter message
        await asyncio.sleep(2)
        author = "inconnu"
        starter_text = "(aucun texte)"
        try:
            starter = await thread.fetch_message(thread.id)
            author = starter.author.display_name
            starter_text = (starter.clean_content or "").strip() or "(pièce jointe)"
        except Exception:
            try:
                async for msg in thread.history(limit=1, oldest_first=True):
                    author = msg.author.display_name
                    starter_text = (msg.clean_content or "").strip() or "(pièce jointe)"
            except Exception as exc:
                logger.warning(
                    "Could not fetch starter message for thread '%s': %s", thread.name, exc
                )

        context = {
            "forum_name": parent.name,
            "forum_id": str(parent.id),
            "thread_name": thread.name,
            "thread_id": str(thread.id),
            "thread_url": thread.jump_url,
            "author": author,
            "starter_message": starter_text[:1500],
        }
        for rule in matching:
            asyncio.create_task(self.execute_rule(rule, context=context))

    async def handle_message_keyword(self, message: discord.Message) -> None:
        """Evaluate `discord_message_keyword` rules on watched guild messages."""
        if not message.guild or message.author.bot:
            return
        content_lower = (message.clean_content or "").lower()
        if not content_lower:
            return

        for rule in self.rules:
            if not rule.enabled or rule.trigger.get("type") != "discord_message_keyword":
                continue
            expected_guild = _parse_optional_int(rule.trigger.get("guild_id"))
            if expected_guild and message.guild.id != expected_guild:
                continue
            keywords = [str(k).lower() for k in rule.trigger.get("keywords", []) if str(k).strip()]
            if not keywords or not any(kw in content_lower for kw in keywords):
                continue

            context = {
                "channel_name": getattr(message.channel, "name", "salon"),
                "author": message.author.display_name,
                "content": (message.clean_content or "")[:1200],
                "message_url": message.jump_url,
            }
            asyncio.create_task(self.execute_rule(rule, context=context))
