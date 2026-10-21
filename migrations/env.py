"""Alembic environment. Everything lives in its own Postgres schema (DB_SCHEMA, default icse_physics),
including the alembic_version table, so it never touches other tables in the same database."""
import os
import re

from alembic import context
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    raise RuntimeError("DATABASE_URL environment variable is not set")
if url.startswith("postgres://"):  # Railway-style URL; psycopg 3 needs the driver name
    url = "postgresql+psycopg" + url[len("postgres"):]
elif url.startswith("postgresql://"):
    url = "postgresql+psycopg" + url[len("postgresql"):]

schema = os.environ.get("DB_SCHEMA", "icse_physics")
if not re.match(r"^[a-z_][a-z0-9_]{0,62}$", schema):
    raise RuntimeError("DB_SCHEMA must be a lowercase identifier such as icse_physics")

if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; run against a database")

engine = create_engine(url)
with engine.connect() as connection:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    connection.execute(text(f"SET search_path TO {schema}"))
    connection.commit()
    context.configure(connection=connection, target_metadata=None, version_table_schema=schema)
    with context.begin_transaction():
        context.run_migrations()
