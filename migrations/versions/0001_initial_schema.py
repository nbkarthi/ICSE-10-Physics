"""Initial schema: students, login events, study days, progress.

Written with IF NOT EXISTS so it also adopts a database that was created by the earlier
create-on-startup code, without losing data.

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
          sub TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL,
          full_name TEXT, school TEXT, profile_completed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_login TIMESTAMPTZ NOT NULL DEFAULT now())
        """
    )
    for col, typ in [("full_name", "TEXT"), ("school", "TEXT"), ("profile_completed_at", "TIMESTAMPTZ")]:
        op.execute(f"ALTER TABLE students ADD COLUMN IF NOT EXISTS {col} {typ}")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS login_events (
          id BIGSERIAL PRIMARY KEY, sub TEXT, email TEXT,
          event TEXT NOT NULL CHECK (event IN ('login', 'logout', 'denied')),
          at TIMESTAMPTZ NOT NULL DEFAULT now(), ip TEXT, user_agent TEXT, method TEXT)
        """
    )
    op.execute("ALTER TABLE login_events ADD COLUMN IF NOT EXISTS method TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS login_events_sub_at ON login_events (sub, at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS study_days (
          sub TEXT NOT NULL REFERENCES students(sub), day DATE NOT NULL, PRIMARY KEY (sub, day))
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
          sub TEXT NOT NULL REFERENCES students(sub), chapter INTEGER NOT NULL, PRIMARY KEY (sub, chapter))
        """
    )


def downgrade() -> None:
    for table in ("progress", "study_days", "login_events", "students"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
