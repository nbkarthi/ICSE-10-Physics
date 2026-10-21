"""Run database migrations.  CLI: `uv run alembic upgrade head` (release step in production)."""
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def run_migrations() -> None:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


if __name__ == "__main__":
    run_migrations()
