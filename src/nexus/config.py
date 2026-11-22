"""Typed application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Runtime
    nexus_env: str = "development"
    log_level: str = "INFO"
    mock_tools: bool = True
    mcp_config_path: Path = Path("config/mcp_servers.yaml")

    # LiteLLM Proxy
    litellm_base_url: str = "http://localhost:4000/v1"
    litellm_master_key: str = "sk-nexus-local-dev-key"
    litellm_fast_model: str = "nexus-fast"
    litellm_smart_model: str = "nexus-smart"

    # PostgreSQL (optional fallback to in-memory checkpointer when unset)
    database_url: str | None = None

    # Discord Bot
    discord_bot_token: str | None = None
    discord_allowed_user_id: int | None = None
    discord_command_center_channel_id: int | None = None
    discord_briefing_channel_id: int | None = None
    discord_gmail_triage_channel_id: int | None = None
    discord_reminders_channel_id: int | None = None
    discord_asso_digest_channel_id: int | None = None
    discord_asso_guild_id: int | None = None
    discord_asso_watch_channel_ids: str | None = None

    # Proactive Scheduler
    timezone: str = "Europe/Paris"
    briefing_hour: int = Field(default=8, ge=0, le=23)
    briefing_minute: int = Field(default=0, ge=0, le=59)
    asso_digest_hour: int = Field(default=20, ge=0, le=23)
    asso_digest_minute: int = Field(default=0, ge=0, le=59)
    gmail_triage_interval_minutes: int = Field(default=60, ge=5)

    # Langfuse Observability (optional)
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    @field_validator(
        "database_url",
        "discord_bot_token",
        "discord_allowed_user_id",
        "discord_command_center_channel_id",
        "discord_briefing_channel_id",
        "discord_gmail_triage_channel_id",
        "discord_reminders_channel_id",
        "discord_asso_digest_channel_id",
        "discord_asso_guild_id",
        "discord_asso_watch_channel_ids",
        "langfuse_host",
        "langfuse_public_key",
        "langfuse_secret_key",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
