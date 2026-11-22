"""Load agent tools either from MCP servers (mcp_servers.yaml) or local mock tools."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool, tool

from nexus.config import get_settings

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


# ------------------------------------------------------------------------------
# Local mock tools (active when MOCK_TOOLS=true for safe day-1 testing)
# ------------------------------------------------------------------------------


@tool
def gmail_list_unread(limit: int = 5) -> str:
    """List recent unread emails from Gmail."""
    emails = [
        {
            "id": "msg_001",
            "from": "president@asso-tech.org",
            "subject": "Compte-rendu AG & tâches serveur Discord",
            "snippet": "Peux-tu valider le créneau de réunion jeudi 19h et mettre à jour Notion ?",
        },
        {
            "id": "msg_002",
            "from": "newsletter@cloudweekly.dev",
            "subject": "Cloud Native Weekly #412",
            "snippet": "Les nouveautés Kubernetes 1.32 et OpenTofu...",
        },
        {
            "id": "msg_003",
            "from": "recrutement@entreprise.fr",
            "subject": "Suite à votre candidature Alternance DevOps",
            "snippet": "Seriez-vous disponible mardi à 14h pour un entretien technique ?",
        },
    ]
    return str(emails[:limit])


@tool
def gmail_apply_label(message_id: str, label: str) -> str:
    """Apply a Gmail label to an email (autonomous action)."""
    return f"[MOCK] Label '{label}' appliqué au message {message_id}."


@tool
def gmail_create_draft(to: str, subject: str, body: str) -> str:
    """Create a Gmail draft reply without sending it (autonomous action)."""
    return f"[MOCK] Brouillon créé pour {to} | Objet: '{subject}'."


@tool
def gmail_send_email(to: str, subject: str, body: str) -> str:
    """Send an email via Gmail (HITL-gated critical action)."""
    return f"[MOCK] Email envoyé à {to} | Objet: '{subject}'."


@tool
def gmail_delete_email(message_id: str) -> str:
    """Permanently delete a Gmail message (HITL-gated critical action)."""
    return f"[MOCK] Message {message_id} supprimé."


@tool
def calendar_list_events(date_range: str = "today") -> str:
    """List upcoming Google Calendar events for a given date range."""
    return (
        f"[MOCK] Agenda ({date_range}):\n"
        "- 10:00-11:30 : Cours Architecture Cloud / Kubernetes\n"
        "- 14:00-15:00 : Créneau libre\n"
        "- 19:00-20:00 : Point Association (à confirmer)"
    )


@tool
def calendar_create_event(title: str, start_iso: str, end_iso: str, attendees: str = "") -> str:
    """Create a Google Calendar event (HITL-gated critical action)."""
    return (
        f"[MOCK] Événement '{title}' créé ({start_iso} -> {end_iso})"
        + (f" avec {attendees}" if attendees else "")
        + "."
    )


@tool
def notion_list_tasks(status: str = "To Do") -> str:
    """List tasks from the personal Notion database."""
    return (
        f"[MOCK] Tâches Notion ({status}):\n"
        "- [Haute] Préparer le déploiement Terraform du VPS\n"
        "- [Moyenne] Répondre au mail d'entretien alternance\n"
        "- [Basse] Nettoyer les newsletters Gmail"
    )


@tool
def notion_create_task(title: str, priority: str = "Moyenne", due_date: str = "") -> str:
    """Create a new task in the personal Notion database (autonomous action)."""
    return f"[MOCK] Tâche Notion créée : '{title}' (Priorité: {priority}, Échéance: {due_date or 'aucune'})."


def get_mock_tools_by_domain() -> dict[str, list[BaseTool]]:
    """Return mock tools grouped by agent domain."""
    return {
        "gmail": [
            gmail_list_unread,
            gmail_apply_label,
            gmail_create_draft,
            gmail_send_email,
            gmail_delete_email,
        ],
        "productivity": [
            calendar_list_events,
            calendar_create_event,
            notion_list_tasks,
            notion_create_task,
        ],
    }


async def load_tools_by_domain(config_path: Path | None = None) -> dict[str, list[BaseTool]]:
    """Load tools per domain using MCP servers when configured, or mock tools in dev mode."""
    settings = get_settings()
    if settings.mock_tools:
        logger.info("MOCK_TOOLS=true — loading local mock tools for Gmail, Calendar & Notion.")
        return get_mock_tools_by_domain()

    path = config_path or settings.mcp_config_path
    if not path.exists():
        logger.warning("MCP config %s not found, falling back to mock tools.", path)
        return get_mock_tools_by_domain()

    raw_cfg = _expand_env(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    servers_cfg: dict[str, dict[str, Any]] = raw_cfg.get("servers", {})

    domain_servers: dict[str, dict[str, dict[str, Any]]] = {}
    for server_name, entry in servers_cfg.items():
        if not entry.get("enabled", False):
            continue
        domain = entry.get("agent", "general")
        connection = {k: v for k, v in entry.items() if k not in {"enabled", "agent"}}
        domain_servers.setdefault(domain, {})[server_name] = connection

    if not domain_servers:
        logger.warning("No enabled MCP servers in %s, falling back to mock tools.", path)
        return get_mock_tools_by_domain()

    from langchain_mcp_adapters.client import MultiServerMCPClient

    mock_fallback = get_mock_tools_by_domain()
    tools_by_domain: dict[str, list[BaseTool]] = {"gmail": [], "productivity": []}
    for domain, connections in domain_servers.items():
        client = MultiServerMCPClient(connections)
        tools = await client.get_tools()
        tools_by_domain.setdefault(domain, []).extend(tools)
        logger.info("Loaded %d MCP tools for domain '%s'.", len(tools), domain)

    # Progressive migration: keep mock tools for domains that have no enabled MCP server yet
    for domain, mock_tools in mock_fallback.items():
        if not tools_by_domain.get(domain):
            logger.info("No enabled MCP server for '%s' yet — keeping mock tools.", domain)
            tools_by_domain[domain] = mock_tools

    return tools_by_domain
