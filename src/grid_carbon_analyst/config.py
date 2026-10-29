"""Settings, read from ``GCA_*`` environment variables (or a ``.env`` file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCA_", env_file=".env", extra="ignore")

    # The lakehouse's DuckDB file. Opened read-only; the agent never writes to it.
    warehouse_path: Path = Path("../uk-grid-carbon-lakehouse/data/warehouse/gridcarbon.duckdb")
    # Any LangChain ``init_chat_model`` string, e.g. "anthropic:claude-sonnet-5-5".
    model: str = "anthropic:claude-sonnet-5-5"
    # Rows returned to the model. More are fetched only to report truncation.
    max_rows: int = 200
    # Wall-clock limit per query; the connection is interrupted after this.
    query_timeout_s: float = 10.0
    # Attempts at writing a query that passes the checks and runs.
    max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
