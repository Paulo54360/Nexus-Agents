"""Real-time log ring-buffer broadcaster and LangChain LLM token usage tracker."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from nexus.storage import MissionControlStore


class LogBroadcaster(logging.Handler):
    """Logging handler storing recent structured entries and streaming them via SSE."""

    def __init__(self, maxlen: int = 400):
        super().__init__()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def emit(self, record: logging.LogRecord) -> None:
        # Ignore noisy healthcheck access logs so the live console stays clean
        msg = self.format(record)
        if "GET /health" in msg or "GET /api/logs" in msg:
            return

        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        self.buffer.append(entry)
        for queue in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(entry)

    def recent(self, limit: int = 150) -> list[dict[str, Any]]:
        return list(self.buffer)[-limit:]

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)


log_broadcaster = LogBroadcaster()


class UsageTrackingCallback(AsyncCallbackHandler):
    """LangChain async callback capturing real token counts & latencies per LLM call."""

    def __init__(self, store: MissionControlStore | None, thread_id: str | None = None):
        super().__init__()
        self.store = store
        self.thread_id = thread_id
        self._starts: dict[UUID, tuple[float, str, str]] = {}

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        meta = metadata or {}
        agent = str(meta.get("langgraph_node") or "supervisor")
        inv_params = kwargs.get("invocation_params") or {}
        model = str(inv_params.get("model_name") or inv_params.get("model") or "litellm")
        self._starts[run_id] = (time.perf_counter(), agent, model)

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        meta = metadata or {}
        agent = str(meta.get("langgraph_node") or "supervisor")
        inv_params = kwargs.get("invocation_params") or {}
        model = str(inv_params.get("model_name") or inv_params.get("model") or "litellm")
        self._starts[run_id] = (time.perf_counter(), agent, model)

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        if not self.store:
            return
        start_ts, agent, fallback_model = self._starts.pop(
            run_id, (time.perf_counter(), "supervisor", "litellm")
        )
        latency_ms = int((time.perf_counter() - start_ts) * 1000)

        llm_output = response.llm_output or {}
        token_usage = llm_output.get("token_usage") or {}
        model = str(llm_output.get("model_name") or fallback_model)

        prompt_tokens = int(token_usage.get("prompt_tokens") or 0)
        completion_tokens = int(token_usage.get("completion_tokens") or 0)
        total_tokens = int(token_usage.get("total_tokens") or (prompt_tokens + completion_tokens))

        # LangChain >= 0.3 / 1.x attaches usage_metadata on the AIMessage
        if total_tokens == 0 and response.generations and response.generations[0]:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            if msg is not None:
                usage_meta = getattr(msg, "usage_metadata", None) or {}
                prompt_tokens = int(usage_meta.get("input_tokens") or prompt_tokens)
                completion_tokens = int(usage_meta.get("output_tokens") or completion_tokens)
                total_tokens = int(
                    usage_meta.get("total_tokens") or (prompt_tokens + completion_tokens)
                )
                resp_meta = getattr(msg, "response_metadata", None) or {}
                if resp_meta.get("model_name"):
                    model = str(resp_meta["model_name"])

        await self.store.record_usage(
            thread_id=self.thread_id,
            agent=agent,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status="ok",
        )

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        if not self.store:
            return
        start_ts, agent, model = self._starts.pop(
            run_id, (time.perf_counter(), "supervisor", "litellm")
        )
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        await self.store.record_usage(
            thread_id=self.thread_id,
            agent=agent,
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=latency_ms,
            status="error",
        )
