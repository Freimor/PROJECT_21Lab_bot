from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from lab21_bot.data import setting_default


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
    main_channel_id: int  # Форум-группа или канал «Будни лабы»
    staff_chat_id: int
    important_channel_id: int | None = None  # если None — тот же чат, что main (топик)
    flood_chat_id: int | None = None  # если None — тот же чат, что main (топик)
    job_chat_id: int | None = None  # отдельный чат заказов; иначе main + job_thread
    job_channel_id: int | None = None  # устаревший алиас JOB_CHANNEL_ID → тот же chat
    shop_chat_id: int | None = None  # витрина магазина; иначе main + shop_thread

    llm_provider: str = "ollama"
    llm_base_url: str = "http://ollama:11434"
    llm_model: str = "lakomoor/vikhr-llama-3.2-1b-instruct:1b"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 120.0

    timezone: str = "Europe/Moscow"
    # Forum topics: MAIN/IMPORTANT/FLOOD may share one chat_id; distinguish by thread_id.
    main_thread_id: int | None = None
    important_thread_id: int | None = None
    flood_thread_id: int | None = None
    job_thread_id: int | None = None
    shop_thread_id: int | None = None
    bugs_chat_id: int | None = None  # канал/чат «Баги предложения»; иначе MAIN
    bugs_thread_id: int | None = None
    content_silence_days: int = Field(default=setting_default("content_silence_days"), ge=1, le=90)
    reminder_hour: int = Field(default=setting_default("reminder_hour"), ge=0, le=23)
    reminder_window_start: int = Field(
        default=setting_default("reminder_window_start"), ge=0, le=23
    )
    reminder_window_end: int = Field(default=setting_default("reminder_window_end"), ge=1, le=24)
    transfer_daily_limit: int = Field(default=setting_default("transfer_daily_limit"), ge=0)
    application_expire_days: int = Field(
        default=setting_default("application_expire_days"), ge=1, le=90
    )
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

    @field_validator(
        "important_channel_id",
        "flood_chat_id",
        "job_chat_id",
        "job_channel_id",
        "main_thread_id",
        "important_thread_id",
        "flood_thread_id",
        "job_thread_id",
        "shop_chat_id",
        "shop_thread_id",
        "bugs_chat_id",
        "bugs_thread_id",
        mode="before",
    )
    @classmethod
    def empty_optional_int(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @field_validator("telegram_bot_username", mode="before")
    @classmethod
    def empty_optional_str(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def resolved_job_chat_id(self) -> int | None:
        return self.job_chat_id if self.job_chat_id is not None else self.job_channel_id

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
