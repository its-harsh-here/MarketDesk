"""Alembic helpers used by the CLI, readiness probe and tests."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

API_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@lru_cache(maxsize=1)
def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
