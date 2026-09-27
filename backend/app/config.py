from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789abcdef"  # noqa: S105


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment (see docs/design/09)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_base_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    api_cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg://estimateai:estimateai@localhost:5432/estimateai"
    redis_url: str = "redis://localhost:6379/0"

    # Auth. In development/test a fixed insecure fallback is used when unset; anywhere else
    # a missing or short secret stops the app from starting.
    secret_key: SecretStr | None = None
    jwt_signing_key: SecretStr | None = None
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_days: int = 30
    cookie_domain: str | None = None

    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = None

    email_provider: Literal["console", "smtp"] = "console"
    email_from: str = "EstimateAI <no-reply@localhost>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None

    # AI is optional: without a key the rules-based extractor is used (docs/design/06 §6.3).
    anthropic_api_key: SecretStr | None = None
    ai_provider: Literal["rules", "mock", "anthropic"] | None = None

    @field_validator("api_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip().startswith("["):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value

    @model_validator(mode="after")
    def _require_secrets_outside_dev(self) -> Settings:
        if self.app_env in ("development", "test"):
            return self
        for name in ("secret_key", "jwt_signing_key"):
            value: SecretStr | None = getattr(self, name)
            if value is None or len(value.get_secret_value()) < 32:
                raise ValueError(f"{name.upper()} must be set (32+ characters) in {self.app_env}.")
        return self

    @property
    def secret(self) -> str:
        return self.secret_key.get_secret_value() if self.secret_key else _DEV_SECRET

    @property
    def jwt_key(self) -> str:
        return self.jwt_signing_key.get_secret_value() if self.jwt_signing_key else _DEV_SECRET

    @property
    def cookie_secure(self) -> bool:
        return self.app_env not in ("development", "test")

    @property
    def google_login_enabled(self) -> bool:
        return bool(
            self.google_oauth_client_id
            and self.google_oauth_client_secret
            and self.google_oauth_redirect_uri
        )

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
