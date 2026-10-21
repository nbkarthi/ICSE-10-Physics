"""ICSE Class 10 Physics server: Google sign-in, gated chapter pages, per-student progress.

Run:  uv run --env-file .env uvicorn server.app:create_app --factory --port 8000
"""
import os
import re
import time
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from psycopg.rows import dict_row
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
CHAPTER_COUNT = 12
SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
GATED_PAGE = re.compile(r"^(index|chapter-\d{2}-[a-z0-9-]+)\.html$")


def _csv(name: str) -> set[str]:
    return {v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()}


def verify_google_credential(credential: str, client_id: str) -> dict:
    """Verify a Google ID token (signature, expiry, audience). Raises ValueError if invalid."""
    return google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


def create_app(verify=verify_google_credential) -> FastAPI:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must be set to a random string of at least 32 characters")
    allowed_emails, allowed_domains = _csv("ALLOWED_EMAILS"), _csv("ALLOWED_DOMAINS")
    db_url = os.environ.get("DATABASE_URL", "")
    schema = os.environ.get("DB_SCHEMA", "icse_physics")
    session_seconds = int(float(os.environ.get("SESSION_HOURS", "24")) * 3600)
    if not db_url:
        raise RuntimeError("DATABASE_URL must be set (Postgres)")
    if not SCHEMA_NAME.match(schema):
        raise RuntimeError("DB_SCHEMA must be a lowercase identifier such as icse_physics")

    def db() -> psycopg.Connection:
        # Own schema keeps these tables apart from anything else in the same database.
        # Used as a context manager: commits on success, rolls back on error, then closes.
        return psycopg.connect(db_url, row_factory=dict_row, options=f"-c search_path={schema}")

    with psycopg.connect(db_url) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
              sub TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              last_login TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS login_events (
              id BIGSERIAL PRIMARY KEY, sub TEXT, email TEXT,
              event TEXT NOT NULL CHECK (event IN ('login', 'logout', 'denied')),
              at TIMESTAMPTZ NOT NULL DEFAULT now(), ip TEXT, user_agent TEXT);
            CREATE INDEX IF NOT EXISTS login_events_sub_at ON login_events (sub, at DESC);
            CREATE TABLE IF NOT EXISTS progress (
              sub TEXT NOT NULL REFERENCES students(sub), chapter INTEGER NOT NULL,
              PRIMARY KEY (sub, chapter));
            """
        )

    def log_event(conn, request: Request, event: str, sub: str | None, email: str | None) -> None:
        ip = request.client.host if request.client else None
        conn.execute(
            "INSERT INTO login_events (sub, email, event, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
            (sub, email, event, ip, (request.headers.get("user-agent") or "")[:300]),
        )

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="icse_session",
        max_age=session_seconds,
        same_site="lax",
        https_only=os.environ.get("COOKIE_SECURE") == "1",
    )

    def current_student(request: Request) -> dict | None:
        student = request.session.get("student")
        # Sessions last a fixed window from sign-in (24 hours by default), then the student signs in again.
        if student and time.time() - student.get("iat", 0) >= session_seconds:
            request.session.clear()
            return None
        return student

    def require_student(request: Request) -> dict:
        student = current_student(request)
        if not student:
            raise HTTPException(status_code=401, detail="Sign in required")
        return student

    @app.get("/api/config")
    def config():
        return {"googleClientId": client_id}

    @app.post("/api/auth/google")
    async def auth_google(request: Request):
        if not client_id:
            raise HTTPException(status_code=503, detail="Google sign-in is not configured")
        body = await request.json()
        credential = body.get("credential") if isinstance(body, dict) else None
        if not isinstance(credential, str) or not credential:
            raise HTTPException(status_code=400, detail="Missing credential")
        try:
            claims = verify(credential, client_id)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid Google token")
        email = str(claims.get("email", "")).lower()
        if not email or claims.get("email_verified") is not True:
            raise HTTPException(status_code=403, detail="Google account email is not verified")
        domain = email.rsplit("@", 1)[-1]
        if (allowed_emails or allowed_domains) and email not in allowed_emails and domain not in allowed_domains:
            with db() as conn:
                log_event(conn, request, "denied", claims.get("sub"), email)
            raise HTTPException(status_code=403, detail="This account is not allowed. Ask your teacher for access.")
        student = {"sub": claims["sub"], "email": email, "name": claims.get("name") or email, "iat": int(time.time())}
        with db() as conn:
            conn.execute(
                """INSERT INTO students (sub, email, name) VALUES (%s, %s, %s)
                   ON CONFLICT (sub) DO UPDATE SET email = EXCLUDED.email, name = EXCLUDED.name, last_login = now()""",
                (student["sub"], student["email"], student["name"]),
            )
            log_event(conn, request, "login", student["sub"], email)
        request.session.clear()
        request.session["student"] = student
        return {"email": email, "name": student["name"]}

    @app.get("/api/me")
    def me(request: Request):
        s = require_student(request)
        return {"email": s["email"], "name": s["name"]}

    @app.post("/api/logout")
    def logout(request: Request):
        student = current_student(request)
        if student:
            with db() as conn:
                log_event(conn, request, "logout", student["sub"], student["email"])
        request.session.clear()
        return {"ok": True}

    @app.get("/api/progress")
    def get_progress(request: Request):
        s = require_student(request)
        with db() as conn:
            rows = conn.execute("SELECT chapter FROM progress WHERE sub = %s ORDER BY chapter", (s["sub"],)).fetchall()
        return {"done": [r["chapter"] for r in rows]}

    @app.put("/api/progress")
    async def put_progress(request: Request):
        s = require_student(request)
        body = await request.json()
        done = body.get("done") if isinstance(body, dict) else None
        if not isinstance(done, list) or not all(
            type(n) is int and 1 <= n <= CHAPTER_COUNT for n in done
        ):
            raise HTTPException(status_code=422, detail=f"done must be a list of chapter numbers 1-{CHAPTER_COUNT}")
        with db() as conn:
            conn.execute("DELETE FROM progress WHERE sub = %s", (s["sub"],))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO progress (sub, chapter) VALUES (%s, %s)", [(s["sub"], n) for n in sorted(set(done))])
        return {"done": sorted(set(done))}

    def page(request: Request, name: str):
        """Serve an HTML page from the repo root. Only allowlisted names; never arbitrary paths."""
        if name == "login.html":
            gated = False
        elif GATED_PAGE.match(name):
            gated = True
        else:
            raise HTTPException(status_code=404)
        path = ROOT / name
        if not path.is_file():
            raise HTTPException(status_code=404)
        if gated and not current_student(request):
            return RedirectResponse("/login.html", status_code=303)
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": "private, no-store"})

    @app.get("/")
    def home(request: Request):
        return page(request, "index.html")

    @app.get("/{name}")
    def named_page(request: Request, name: str):
        return page(request, name)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
