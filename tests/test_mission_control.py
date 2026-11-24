"""Unit tests for Mission Control persistence, telemetry, and automation controls."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nexus.automations.engine import AutomationEngine
from nexus.storage import MissionControlStore, infer_provider
from nexus.telemetry import LogBroadcaster


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("mistral/mistral-medium-latest", "Mistral"),
        ("groq/openai/gpt-oss-120b", "Groq"),
        ("gemini/gemini-3.5-flash-lite", "Gemini"),
        ("nexus-fast", "Groq (fast)"),
        ("nexus-smart", "Mistral (smart)"),
        ("custom-unknown", "LiteLLM"),
    ],
)
def test_infer_provider(model: str, expected: str) -> None:
    assert infer_provider(model) == expected


@pytest.mark.asyncio
async def test_mission_control_store_in_memory_threads_and_usage() -> None:
    store = MissionControlStore(pool=None)
    await store.ensure_schema()

    created = await store.create_thread(title="Nouvelle conversation", category="asso")
    tid = created["id"]
    assert tid.startswith("web-")

    # Auto-title should replace the default placeholder on first prompt
    await store.touch_thread(tid, auto_title="Résumé du serveur staff")
    threads = await store.list_threads()
    assert len(threads) == 1
    assert threads[0]["title"] == "Résumé du serveur staff"

    renamed = await store.rename_thread(tid, title="Veille Asso", category="asso")
    assert renamed is not None
    assert renamed["title"] == "Veille Asso"

    await store.record_usage(
        thread_id=tid,
        agent="asso_agent",
        model="mistral/mistral-medium-latest",
        prompt_tokens=400,
        completion_tokens=150,
        total_tokens=550,
        latency_ms=820,
        status="ok",
    )
    stats = await store.get_usage_stats(days=7)
    assert stats["summary"]["total_tokens"] == 550
    assert stats["summary"]["total_calls"] == 1
    assert stats["summary"]["estimated_cost_eur"] == 0.0
    assert stats["recent"][0]["provider"] == "Mistral"

    assert await store.delete_thread(tid) is True
    assert await store.list_threads() == []


def test_log_broadcaster_filters_healthcheck_and_buffers() -> None:
    broadcaster = LogBroadcaster(maxlen=10)
    queue = broadcaster.subscribe()

    noisy = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, "GET /health HTTP/1.1 200", (), None
    )
    normal = logging.LogRecord(
        "nexus.runtime", logging.INFO, "", 0, "Agent completed turn", (), None
    )

    broadcaster.emit(noisy)
    broadcaster.emit(normal)

    recent = broadcaster.recent()
    assert len(recent) == 1
    assert recent[0]["message"] == "Agent completed turn"
    assert queue.qsize() == 1

    broadcaster.unsubscribe(queue)


def test_automation_engine_list_and_toggle(tmp_path: Path) -> None:
    cfg = tmp_path / "automations.yaml"
    cfg.write_text(
        """
automations:
  - id: test-rule
    name: "Test Rule"
    enabled: true
    trigger:
      type: cron
      hour: 8
    prompt: "Bonjour"
""",
        encoding="utf-8",
    )
    engine = AutomationEngine(graph=None, config_path=cfg)
    rules = engine.list_rules_data()
    assert len(rules) == 1
    assert rules[0]["enabled"] is True

    toggled = engine.toggle_rule("test-rule")
    assert toggled is not None
    assert toggled["enabled"] is False
    assert engine.toggle_rule("missing-rule") is None
