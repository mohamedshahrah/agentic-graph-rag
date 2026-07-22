"""Typed configuration. `Settings` mirrors the YAML; `Secrets` reads connection
strings and keys from the environment (.env)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppCfg(BaseModel):
    name: str = "llmlens"
    log_level: str = "INFO"
    retention_days: int = 30


class IngestCfg(BaseModel):
    queue_stream: str = "llmlens:ingest"
    consumer_group: str = "writers"
    batch_max_events: int = 1000
    batch_max_seconds: int = 2
    record_content: bool = True


class AlertingCfg(BaseModel):
    enabled: bool = True
    interval_seconds: int = 60
    default_cooldown_seconds: int = 900


class APICfg(BaseModel):
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    cors_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    cors_headers: list[str] = Field(
        default_factory=lambda: ["Content-Type", "Authorization", "X-Api-Key", "X-Admin-Key"]
    )
    rate_limit: str = "600/minute"


class AuthCfg(BaseModel):
    enabled: bool = True


class Settings(BaseModel):
    app: AppCfg = Field(default_factory=AppCfg)
    ingest: IngestCfg = Field(default_factory=IngestCfg)
    alerting: AlertingCfg = Field(default_factory=AlertingCfg)
    api: APICfg = Field(default_factory=APICfg)
    auth: AuthCfg = Field(default_factory=AuthCfg)


class Secrets(BaseSettings):
    """Connection details + secrets, read from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    profile: str = Field(default="default", alias="LLMLENS_PROFILE")

    clickhouse_host: str = Field(default="localhost", alias="LLMLENS_CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=8123, alias="LLMLENS_CLICKHOUSE_PORT")
    clickhouse_user: str = Field(default="default", alias="LLMLENS_CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="", alias="LLMLENS_CLICKHOUSE_PASSWORD")
    clickhouse_db: str = Field(default="llmlens", alias="LLMLENS_CLICKHOUSE_DB")

    postgres_dsn: str = Field(
        default="postgresql://llmlens:please-change-me@localhost:5432/llmlens",
        alias="LLMLENS_POSTGRES_DSN",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="LLMLENS_REDIS_URL")

    admin_key: str = Field(default="change-me-admin", alias="LLMLENS_ADMIN_KEY")
