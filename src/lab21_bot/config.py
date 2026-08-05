from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: SecretStr
    bootstrap_magister_id: int
    database_url: str = "postgresql+asyncpg://lab21:lab21@postgres:5432/lab21"
    main_channel_id: int
    staff_chat_id: int
    flood_chat_id: int | None = None

    llm_provider: str = "ollama"
    llm_base_url: str = "http://ollama:11434"
    llm_model: str = "qwen3:4b"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120.0

    timezone: str = "Europe/Moscow"
    content_silence_days: int = Field(default=3, ge=1, le=90)
    reminder_hour: int = Field(default=14, ge=0, le=23)
    reminder_window_start: int = Field(default=12, ge=0, le=23)
    reminder_window_end: int = Field(default=20, ge=1, le=24)
    transfer_daily_limit: int = Field(default=100, ge=0)
    application_expire_days: int = Field(default=7, ge=1, le=90)
    upload_dir: str = "/app/uploads"
    log_level: str = "INFO"

    control_dir: str = "/control"
    app_git_sha: str = "unknown"
    github_repo: str = "Freimor/PROJECT_21Lab_bot"
    github_branch: str = "main"
    github_token: SecretStr | None = None

    admin_enabled: bool = True
    admin_host: str = "0.0.0.0"
    admin_port: int = Field(default=8080, ge=1, le=65535)
    admin_base_url: str = "http://localhost:8080"
    admin_session_secret: SecretStr | None = None
    admin_password: SecretStr | None = None
    telegram_bot_username: str | None = None

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in {"ollama", "openai"}:
            raise ValueError("llm_provider must be 'ollama' or 'openai'")
        return normalized

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def session_secret(self) -> str:
        if self.admin_session_secret is not None:
            return self.admin_session_secret.get_secret_value()
        # Dev fallback: stable secret derived from bot token.
        return f"lab21-admin:{self.telegram_bot_token.get_secret_value()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
