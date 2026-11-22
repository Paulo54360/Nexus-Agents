"""LLM factory routing all model calls through LiteLLM Proxy + optional Langfuse tracing."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Literal

from langchain_openai import ChatOpenAI

from nexus.config import get_settings

logger = logging.getLogger(__name__)

ModelTier = Literal["fast", "smart"]


def get_llm(tier: ModelTier = "fast", temperature: float = 0.2) -> ChatOpenAI:
    """Return a ChatOpenAI client backed by the self-hosted LiteLLM proxy."""
    settings = get_settings()
    model_name = settings.litellm_fast_model if tier == "fast" else settings.litellm_smart_model
    return ChatOpenAI(
        model=model_name,
        api_key=settings.litellm_master_key,
        base_url=settings.litellm_base_url,
        temperature=temperature,
    )


@lru_cache(maxsize=1)
def _init_langfuse_client():
    """Initialize the Langfuse singleton client once so CallbackHandler can attach to it."""
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None

    host = settings.langfuse_host or "https://cloud.langfuse.com"
    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = host
    os.environ["LANGFUSE_BASE_URL"] = host

    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=host,
        )
    except Exception as exc:  # pragma: no cover - optional telemetry must never break agents
        logger.warning("Langfuse client initialization failed: %s", exc)
        return None


def get_langfuse_callbacks(session_id: str | None = None, user_id: str | None = None) -> list:
    """Return Langfuse LangChain callback handlers (SDK v3+/v5+) when configured."""
    client = _init_langfuse_client()
    if client is None:
        return []

    settings = get_settings()
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler(public_key=settings.langfuse_public_key)]
    except Exception as exc:  # pragma: no cover - optional telemetry must never break agents
        logger.warning("Langfuse callback unavailable: %s", exc)
        return []


def flush_langfuse() -> None:
    """Flush pending Langfuse traces to Langfuse Cloud / self-hosted immediately."""
    client = _init_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to flush Langfuse client: %s", exc)
