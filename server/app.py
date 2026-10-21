"""ICSE Class 10 Physics server: Google sign-in, gated chapter pages, per-student progress.

Run:  uv run --env-file .env uvicorn server.app:create_app --factory --port 8000
"""
import hmac
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from zoneinfo import ZoneInfo

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from psycopg.rows import dict_row
from starlette.middleware.sessions import SessionMiddleware

ROOT = Path(__file__).resolve().parent.parent
CHAPTER_COUNT = 12
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MAX_FAILED_LOGINS, FAILED_WINDOW = 10, 15 * 60
SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
CHAPTER_PAGE = re.compile(r"^chapter-\d{2}-[a-z0-9-]+\.html$")
GATED_PAGE = re.compile(r"^(index|chapter-\d{2}-[a-z0-9-]+)\.html$")


def _csv(name: str) -> set[str]:
    return {v.strip().lower() for v in os.environ.get(name, "").split(",") if v.strip()}


def verify_google_credential(credential: str, client_id: str) -> dict:
    """Verify a Google ID token (signature, expiry, audience). Raises ValueError if invalid."""
    return google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


def streaks(days: list[date], today: date) -> tuple[int, int]:
    """Return (current, longest) run of consecutive study days. A streak stays alive until the end of the next day."""
    ds = sorted(set(days))
    longest = run = 0
    prev = None
    for d in ds:
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        longest = max(longest, run)
        prev = d
    current = 0
    if ds and today - ds[-1] <= timedelta(days=1):
        current = run
    return current, longest


BADGES = [
    ("first-steps", "First steps", "Open your first chapter", lambda c, l, n, d: d >= 1),
    ("chapter-done", "Chapter complete", "Finish one chapter", lambda c, l, n, d: n >= 1),
    ("halfway", "Halfway there", "Finish 6 chapters", lambda c, l, n, d: n >= 6),
    ("physics-pro", "Physics pro", "Finish all 12 chapters", lambda c, l, n, d: n >= 12),
    ("streak-3", "3-day streak", "Study 3 days in a row", lambda c, l, n, d: l >= 3),
    ("streak-7", "7-day streak", "Study 7 days in a row", lambda c, l, n, d: l >= 7),
    ("streak-30", "30-day streak", "Study 30 days in a row", lambda c, l, n, d: l >= 30),
]


def create_app(verify=verify_google_credential) -> FastAPI:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    secret = os.environ.get("SESSION_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SESSION_SECRET must be set to a random string of at least 32 characters")
    allowed_emails, allowed_domains = _csv("ALLOWED_EMAILS"), _csv("ALLOWED_DOMAINS")
    db_url = os.environ.get("DATABASE_URL", "")
    schema = os.environ.get("DB_SCHEMA", "icse_physics")
    session_seconds = int(float(os.environ.get("SESSION_HOURS", "24")) * 3600)
    default_password = os.environ.get("DEFAULT_PASSWORD", "")
    failed: dict[str, list[float]] = {}
    tz = ZoneInfo(os.environ.get("STUDY_TIMEZONE", "Asia/Kolkata"))
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
            ALTER TABLE students ADD COLUMN IF NOT EXISTS full_name TEXT;
            ALTER TABLE students ADD COLUMN IF NOT EXISTS school TEXT;
            ALTER TABLE students ADD COLUMN IF NOT EXISTS profile_completed_at TIMESTAMPTZ;
            CREATE TABLE IF NOT EXISTS login_events (
              id BIGSERIAL PRIMARY KEY, sub TEXT, email TEXT,
              event TEXT NOT NULL CHECK (event IN ('login', 'logout', 'denied')),
              at TIMESTAMPTZ NOT NULL DEFAULT now(), ip TEXT, user_agent TEXT);
            ALTER TABLE login_events ADD COLUMN IF NOT EXISTS method TEXT;
            CREATE INDEX IF NOT EXISTS login_events_sub_at ON login_events (sub, at DESC);
            CREATE TABLE IF NOT EXISTS study_days (
              sub TEXT NOT NULL REFERENCES students(sub), day DATE NOT NULL,
              PRIMARY KEY (sub, day));
            CREATE TABLE IF NOT EXISTS progress (
              sub TEXT NOT NULL REFERENCES students(sub), chapter INTEGER NOT NULL,
              PRIMARY KEY (sub, chapter));
            """
        )

    def log_event(conn, request: Request, event: str, sub: str | None, email: str | None, method: str = "google") -> None:
        ip = request.client.host if request.client else None
        conn.execute(
            "INSERT INTO login_events (sub, email, event, ip, user_agent, method) VALUES (%s, %s, %s, %s, %s, %s)",
            (sub, email, event, ip, (request.headers.get("user-agent") or "")[:300], method),
        )

    def is_allowed(email: str) -> bool:
        if not (allowed_emails or allowed_domains):
            return True
        return email in allowed_emails or email.rsplit("@", 1)[-1] in allowed_domains

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
        return {"googleClientId": client_id, "passwordLogin": bool(default_password)}

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
        if not is_allowed(email):
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

    def load_profile(sub: str) -> dict:
        with db() as conn:
            row = conn.execute(
                "SELECT name, email, full_name, school, profile_completed_at FROM students WHERE sub = %s", (sub,)
            ).fetchone()
        if not row:
            return {"profileComplete": False}
        return {
            "email": row["email"],
            "name": row["full_name"] or row["name"],
            "fullName": row["full_name"] or "",
            "school": row["school"] or "",
            "profileComplete": row["profile_completed_at"] is not None,
        }

    @app.post("/api/auth/password")
    async def auth_password(request: Request):
        """Sign in with the shared class password. Only available when DEFAULT_PASSWORD is set on the server."""
        if not default_password:
            raise HTTPException(status_code=404)
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        recent = [t for t in failed.get(ip, []) if now - t < FAILED_WINDOW]
        failed[ip] = recent
        if len(recent) >= MAX_FAILED_LOGINS:
            raise HTTPException(status_code=429, detail="Too many wrong attempts. Try again in 15 minutes.")
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Invalid request")
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        if not EMAIL.match(email):
            raise HTTPException(status_code=422, detail="Enter a valid email address.")
        if not hmac.compare_digest(password.encode(), default_password.encode()):
            failed[ip].append(now)
            with db() as conn:
                log_event(conn, request, "denied", None, email, "password")
            raise HTTPException(status_code=401, detail="Wrong email or password.")
        if not is_allowed(email):
            with db() as conn:
                log_event(conn, request, "denied", None, email, "password")
            raise HTTPException(status_code=403, detail="This account is not allowed. Ask your teacher for access.")
        failed.pop(ip, None)
        sub = "pw:" + email
        student = {"sub": sub, "email": email, "name": email.split("@")[0], "iat": int(now)}
        with db() as conn:
            conn.execute(
                """INSERT INTO students (sub, email, name) VALUES (%s, %s, %s)
                   ON CONFLICT (sub) DO UPDATE SET last_login = now()""",
                (sub, email, student["name"]),
            )
            log_event(conn, request, "login", sub, email, "password")
        request.session.clear()
        request.session["student"] = student
        return load_profile(sub)

    @app.get("/api/me")
    def me(request: Request):
        return load_profile(require_student(request)["sub"])

    @app.put("/api/profile")
    async def put_profile(request: Request):
        s = require_student(request)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Invalid profile")
        full_name = " ".join(str(body.get("fullName", "")).split())
        school = " ".join(str(body.get("school", "")).split())
        if not 2 <= len(full_name) <= 80 or not full_name.replace(" ", "").isprintable():
            raise HTTPException(status_code=422, detail="Enter your full name (2 to 80 characters).")
        if len(school) > 100 or not (school.replace(" ", "") or "x").isprintable():
            raise HTTPException(status_code=422, detail="School name is too long (100 characters at most).")
        with db() as conn:
            conn.execute(
                """UPDATE students SET full_name = %s, school = %s,
                   profile_completed_at = COALESCE(profile_completed_at, now()) WHERE sub = %s""",
                (full_name, school or None, s["sub"]),
            )
        return load_profile(s["sub"])

    def today() -> date:
        return datetime.fromtimestamp(time.time(), tz).date()

    @app.get("/api/streak")
    def get_streak(request: Request):
        sub = require_student(request)["sub"]
        with db() as conn:
            days = [r["day"] for r in conn.execute("SELECT day FROM study_days WHERE sub = %s", (sub,)).fetchall()]
            done = conn.execute("SELECT count(*) AS n FROM progress WHERE sub = %s", (sub,)).fetchone()["n"]
        current, longest = streaks(days, today())
        return {
            "current": current,
            "longest": longest,
            "badges": [
                {"id": i, "name": n, "description": d, "earned": bool(rule(current, longest, done, len(set(days))))}
                for i, n, d, rule in BADGES
            ],
        }

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
        elif name == "profile.html":
            gated = True
        elif GATED_PAGE.match(name):
            gated = True
        else:
            raise HTTPException(status_code=404)
        path = ROOT / name
        if not path.is_file():
            raise HTTPException(status_code=404)
        if gated:
            student = current_student(request)
            if not student:
                return RedirectResponse("/login.html", status_code=303)
            # First sign-in: collect the student's basic details before showing any lesson.
            if name != "profile.html" and not load_profile(student["sub"])["profileComplete"]:
                return RedirectResponse("/profile.html", status_code=303)
            if CHAPTER_PAGE.match(name):
                with db() as conn:
                    conn.execute(
                        "INSERT INTO study_days (sub, day) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (student["sub"], today()),
                    )
        return FileResponse(path, media_type="text/html", headers={"Cache-Control": "private, no-store"})

    @app.get("/")
    def home(request: Request):
        return page(request, "index.html")

    @app.get("/theme.js")
    def theme_script():
        return FileResponse(ROOT / "theme.js", media_type="text/javascript")

    @app.get("/{name}")
    def named_page(request: Request, name: str):
        return page(request, name)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app
