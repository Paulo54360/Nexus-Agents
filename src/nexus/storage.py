"""PostgreSQL persistence for Multi-Chat threads and FinOps LLM token usage telemetry."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nexus_threads (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nexus_usage_events (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT,
    agent TEXT NOT NULL DEFAULT 'supervisor',
    model TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'litellm',
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nexus_usage_created_at ON nexus_usage_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nexus_threads_updated_at ON nexus_threads (updated_at DESC);
"""


def infer_provider(model_name: str) -> str:
    """Infer LLM provider label from a LiteLLM / model identifier."""
    lower = (model_name or "").lower()
    if "mistral" in lower or "ministral" in lower or "codestral" in lower:
        return "Mistral"
    if "groq" in lower or "gpt-oss" in lower or "llama" in lower or "qwen" in lower:
        return "Groq"
    if "gemini" in lower:
        return "Gemini"
    if "ollama" in lower:
        return "Ollama"
    if "gpt-" in lower or "openai" in lower:
        return "OpenAI / GitHub"
    if "nexus-fast" in lower:
        return "Groq (fast)"
    if "nexus-smart" in lower:
        return "Mistral (smart)"
    return "LiteLLM"


class MissionControlStore:
    """Async repository backed by psycopg AsyncConnectionPool (with in-memory fallback)."""

    def __init__(self, pool: Any | None = None):
        self.pool = pool
        self._mem_threads: dict[str, dict[str, Any]] = {}
        self._mem_usage: list[dict[str, Any]] = []

    async def ensure_schema(self) -> None:
        if not self.pool:
            return
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_SCHEMA_SQL)
        logger.info("Mission Control PostgreSQL tables ready.")

    # ------------------------------------------------------------------
    # Multi-Chat Threads
    # ------------------------------------------------------------------

    async def list_threads(self) -> list[dict[str, Any]]:
        if not self.pool:
            return sorted(
                self._mem_threads.values(),
                key=lambda t: t["updated_at"],
                reverse=True,
            )
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id, title, category, created_at, updated_at "
                "FROM nexus_threads ORDER BY updated_at DESC LIMIT 100"
            )
            rows = await cur.fetchall()
        return [
            {
                "id": r[0],
                "title": r[1],
                "category": r[2],
                "created_at": r[3].isoformat(),
                "updated_at": r[4].isoformat(),
            }
            for r in rows
        ]

    async def create_thread(
        self,
        title: str = "Nouvelle conversation",
        category: str = "general",
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        tid = thread_id or f"web-{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC)
        if not self.pool:
            entry = {
                "id": tid,
                "title": title,
                "category": category,
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
            self._mem_threads[tid] = entry
            return entry

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO nexus_threads (id, title, category, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET updated_at = NOW()
                RETURNING id, title, category, created_at, updated_at
                """,
                (tid, title, category),
            )
            row = await cur.fetchone()
        return {
            "id": row[0],
            "title": row[1],
            "category": row[2],
            "created_at": row[3].isoformat(),
            "updated_at": row[4].isoformat(),
        }

    async def touch_thread(self, thread_id: str, auto_title: str | None = None) -> None:
        """Ensure thread exists, update updated_at, and optionally replace default title."""
        clean_title = (auto_title or "").strip()[:64]
        if not self.pool:
            existing = self._mem_threads.get(thread_id)
            now = datetime.now(UTC).isoformat()
            if not existing:
                self._mem_threads[thread_id] = {
                    "id": thread_id,
                    "title": clean_title or thread_id,
                    "category": "general",
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                existing["updated_at"] = now
                if clean_title and existing["title"] == "Nouvelle conversation":
                    existing["title"] = clean_title
            return

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO nexus_threads (id, title, category, created_at, updated_at)
                VALUES (%s, %s, 'general', NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    updated_at = NOW(),
                    title = CASE
                        WHEN nexus_threads.title = 'Nouvelle conversation' AND %s <> '' THEN %s
                        ELSE nexus_threads.title
                    END
                """,
                (thread_id, clean_title or thread_id, clean_title, clean_title),
            )

    async def rename_thread(
        self, thread_id: str, title: str, category: str | None = None
    ) -> dict[str, Any] | None:
        if not self.pool:
            entry = self._mem_threads.get(thread_id)
            if not entry:
                return None
            entry["title"] = title
            if category:
                entry["category"] = category
            entry["updated_at"] = datetime.now(UTC).isoformat()
            return entry

        async with self.pool.connection() as conn, conn.cursor() as cur:
            if category:
                await cur.execute(
                    "UPDATE nexus_threads SET title = %s, category = %s, updated_at = NOW() "
                    "WHERE id = %s RETURNING id, title, category, created_at, updated_at",
                    (title, category, thread_id),
                )
            else:
                await cur.execute(
                    "UPDATE nexus_threads SET title = %s, updated_at = NOW() "
                    "WHERE id = %s RETURNING id, title, category, created_at, updated_at",
                    (title, thread_id),
                )
            row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "category": row[2],
            "created_at": row[3].isoformat(),
            "updated_at": row[4].isoformat(),
        }

    async def delete_thread(self, thread_id: str) -> bool:
        if not self.pool:
            return self._mem_threads.pop(thread_id, None) is not None
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("DELETE FROM nexus_threads WHERE id = %s", (thread_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # FinOps Token Usage Telemetry
    # ------------------------------------------------------------------

    async def record_usage(
        self,
        *,
        thread_id: str | None,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str = "ok",
    ) -> None:
        provider = infer_provider(model)
        if not self.pool:
            self._mem_usage.append(
                {
                    "thread_id": thread_id,
                    "agent": agent,
                    "model": model,
                    "provider": provider,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "latency_ms": latency_ms,
                    "status": status,
                    "created_at": datetime.now(UTC).isoformat(),
                }
            )
            return

        try:
            async with self.pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO nexus_usage_events
                        (thread_id, agent, model, provider, prompt_tokens, completion_tokens,
                         total_tokens, latency_ms, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        thread_id,
                        agent,
                        model,
                        provider,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        latency_ms,
                        status,
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to persist usage telemetry: %s", exc)

    async def get_usage_stats(self, days: int = 7) -> dict[str, Any]:
        days = max(1, min(days, 90))
        if not self.pool:
            total_tokens = sum(e["total_tokens"] for e in self._mem_usage)
            total_calls = len(self._mem_usage)
            avg_lat = (
                int(sum(e["latency_ms"] for e in self._mem_usage) / total_calls)
                if total_calls
                else 0
            )
            return {
                "days": days,
                "summary": {
                    "total_tokens": total_tokens,
                    "prompt_tokens": sum(e["prompt_tokens"] for e in self._mem_usage),
                    "completion_tokens": sum(e["completion_tokens"] for e in self._mem_usage),
                    "total_calls": total_calls,
                    "avg_latency_ms": avg_lat,
                    "error_calls": sum(1 for e in self._mem_usage if e["status"] != "ok"),
                    "estimated_cost_eur": 0.0,
                },
                "by_day": [],
                "by_model": [],
                "by_agent": [],
                "recent": list(reversed(self._mem_usage[-20:])),
            }

        interval_str = f"{days} days"
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    COALESCE(SUM(total_tokens), 0),
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0),
                    COUNT(*),
                    COALESCE(AVG(latency_ms), 0)::INT,
                    COALESCE(SUM(CASE WHEN status <> 'ok' THEN 1 ELSE 0 END), 0)
                FROM nexus_usage_events
                WHERE created_at >= NOW() - %s::INTERVAL
                """,
                (interval_str,),
            )
            s = await cur.fetchone()

            await cur.execute(
                """
                SELECT
                    TO_CHAR(DATE_TRUNC('day', created_at), 'YYYY-MM-DD') AS day,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt,
                    COALESCE(SUM(completion_tokens), 0) AS completion,
                    COALESCE(SUM(total_tokens), 0) AS total,
                    COUNT(*) AS calls
                FROM nexus_usage_events
                WHERE created_at >= NOW() - %s::INTERVAL
                GROUP BY 1
                ORDER BY 1 ASC
                """,
                (interval_str,),
            )
            by_day = [
                {
                    "day": r[0],
                    "prompt_tokens": int(r[1]),
                    "completion_tokens": int(r[2]),
                    "total_tokens": int(r[3]),
                    "calls": int(r[4]),
                }
                for r in await cur.fetchall()
            ]

            await cur.execute(
                """
                SELECT
                    model,
                    provider,
                    COALESCE(SUM(total_tokens), 0) AS total,
                    COUNT(*) AS calls,
                    COALESCE(AVG(latency_ms), 0)::INT AS avg_ms
                FROM nexus_usage_events
                WHERE created_at >= NOW() - %s::INTERVAL
                GROUP BY model, provider
                ORDER BY total DESC
                """,
                (interval_str,),
            )
            by_model = [
                {
                    "model": r[0],
                    "provider": r[1],
                    "total_tokens": int(r[2]),
                    "calls": int(r[3]),
                    "avg_latency_ms": int(r[4]),
                }
                for r in await cur.fetchall()
            ]

            await cur.execute(
                """
                SELECT
                    agent,
                    COALESCE(SUM(total_tokens), 0) AS total,
                    COUNT(*) AS calls,
                    COALESCE(AVG(latency_ms), 0)::INT AS avg_ms
                FROM nexus_usage_events
                WHERE created_at >= NOW() - %s::INTERVAL
                GROUP BY agent
                ORDER BY total DESC
                """,
                (interval_str,),
            )
            by_agent = [
                {
                    "agent": r[0],
                    "total_tokens": int(r[1]),
                    "calls": int(r[2]),
                    "avg_latency_ms": int(r[3]),
                }
                for r in await cur.fetchall()
            ]

            await cur.execute(
                """
                SELECT id, thread_id, agent, model, provider, prompt_tokens, completion_tokens,
                       total_tokens, latency_ms, status, created_at
                FROM nexus_usage_events
                ORDER BY created_at DESC
                LIMIT 25
                """
            )
            recent = [
                {
                    "id": int(r[0]),
                    "thread_id": r[1],
                    "agent": r[2],
                    "model": r[3],
                    "provider": r[4],
                    "prompt_tokens": int(r[5]),
                    "completion_tokens": int(r[6]),
                    "total_tokens": int(r[7]),
                    "latency_ms": int(r[8]),
                    "status": r[9],
                    "created_at": r[10].isoformat(),
                }
                for r in await cur.fetchall()
            ]

        return {
            "days": days,
            "summary": {
                "total_tokens": int(s[0]),
                "prompt_tokens": int(s[1]),
                "completion_tokens": int(s[2]),
                "total_calls": int(s[3]),
                "avg_latency_ms": int(s[4]),
                "error_calls": int(s[5]),
                "estimated_cost_eur": 0.0,
            },
            "by_day": by_day,
            "by_model": by_model,
            "by_agent": by_agent,
            "recent": recent,
        }
