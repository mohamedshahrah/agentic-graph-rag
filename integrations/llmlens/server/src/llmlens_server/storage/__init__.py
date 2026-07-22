"""Storage setup: apply ClickHouse + Postgres schemas and seed pricing."""

from __future__ import annotations

from llmlens_server.config.settings import Secrets, Settings
from llmlens_server.pricing.seed import SEED_PRICING
from llmlens_server.storage import clickhouse, postgres


def setup_storage(settings: Settings, secrets: Secrets) -> None:
    clickhouse.apply_schema(settings, secrets)
    postgres.apply_schema(secrets.postgres_dsn)
    with postgres.connect(secrets.postgres_dsn) as conn:
        for provider, model, inp, out in SEED_PRICING:
            postgres.repos.upsert_price(conn, provider, model, inp, out)


__all__ = ["setup_storage", "clickhouse", "postgres"]
