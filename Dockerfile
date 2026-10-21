FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000
# Migrations run as a release step (railway.json preDeployCommand), not here, so several instances never race.
CMD ["sh", "-c", "uv run --no-sync uvicorn server.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
