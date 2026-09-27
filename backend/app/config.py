from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment (see docs/design/09)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg://estimateai:estimateai@localhost:5432/estimateai"
    redis_url: str = "redis://localhost:6379/0"

    # AI is optional: without a key the rules-based extractor is used (docs/design/06 §6.3).
    anthropic_api_key: SecretStr | None = None
    ai_provider: Literal["rules", "mock", "anthropic"] | None = None

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @property
    def effective_ai_provider(self) -> str:
        if self.ai_provider:
            return self.ai_provider
        return "anthropic" if self.anthropic_api_key else "rules"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
