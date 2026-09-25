"""Database migrations (Alembic), usable without an alembic.ini."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import settings


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def make_revision(message: str) -> None:
    command.revision(alembic_config(), message=message, autogenerate=True)
