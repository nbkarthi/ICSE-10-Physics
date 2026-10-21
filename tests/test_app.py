import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from datetime import date

from server.app import create_app, streaks

CLIENT_ID = "test-client.apps.googleusercontent.com"
GOOD = {"sub": "123", "email": "Kid@Gmail.com", "email_verified": True, "name": "Kid One"}


def fake_verify(credential, client_id):
    assert client_id == CLIENT_ID
    if credential == "good":
        return dict(GOOD)
    if credential == "unverified":
        return {**GOOD, "email_verified": False}
    raise ValueError("bad token")


TEST_SCHEMA = "icse_physics_test"
DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://localhost/railway")


@pytest.fixture(autouse=True)
def fresh_schema(monkeypatch):
    """Each test gets an empty throwaway schema; only that schema is ever dropped."""
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("DB_SCHEMA", TEST_SCHEMA)
    monkeypatch.setenv("AUTO_MIGRATE", "1")
    yield
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")


def rows(sql):
    with psycopg.connect(DB_URL, options=f"-c search_path={TEST_SCHEMA}") as conn:
        return conn.execute(sql).fetchall()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    monkeypatch.delenv("ALLOWED_DOMAINS", raising=False)
    return TestClient(create_app(verify=fake_verify), follow_redirects=False)


def login(c, cred="good"):
    return c.post("/api/auth/google", json={"credential": cred})


def complete_profile(c, name="Kid One Sharma", school="Demo School"):
    return c.put("/api/profile", json={"fullName": name, "school": school})


def test_requires_secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(RuntimeError):
        create_app()


def test_pages_gated(client):
    assert client.get("/").status_code == 303
    assert client.get("/chapter-01-force.html").headers["location"] == "/login.html"
    assert client.get("/login.html").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_no_arbitrary_files(client):
    login(client)
    complete_profile(client)
    for name in ["CLAUDE.md", ".env", "pyproject.toml", "server", "chapter-01-force.html.bak"]:
        assert client.get(f"/{name}").status_code == 404
    assert client.get("/%2e%2e/etc/passwd").status_code == 404


def test_login_flow_and_pages(client):
    r = login(client)
    assert r.status_code == 200 and r.json()["email"] == "kid@gmail.com"
    assert client.get("/api/me").json()["name"] == "Kid One"
    complete_profile(client)
    assert client.get("/api/me").json()["name"] == "Kid One Sharma"
    assert client.get("/").status_code == 200
    assert client.get("/chapter-01-force.html").status_code == 200
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401
    assert client.get("/").status_code == 303


def test_bad_tokens(client):
    assert login(client, "nope").status_code == 401
    assert login(client, "unverified").status_code == 403
    assert client.post("/api/auth/google", json={}).status_code == 400


def test_allowlist(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("ALLOWED_DOMAINS", "school.org")
    c = TestClient(create_app(verify=fake_verify))
    assert login(c).status_code == 403
    monkeypatch.setenv("ALLOWED_EMAILS", "kid@gmail.com")
    c = TestClient(create_app(verify=fake_verify))
    assert login(c).status_code == 200


def test_progress(client):
    assert client.get("/api/progress").status_code == 401
    login(client)
    assert client.get("/api/progress").json() == {"done": []}
    assert client.put("/api/progress", json={"done": [4, 1, 1]}).json() == {"done": [1, 4]}
    assert client.get("/api/progress").json() == {"done": [1, 4]}
    for bad in [{"done": [0]}, {"done": [13]}, {"done": ["1"]}, {"done": [True]}, {"done": 1}]:
        assert client.put("/api/progress", json=bad).status_code == 422


def test_login_events_tracked(client):
    login(client)
    client.post("/api/logout")
    login(client, "nope")  # failed tokens are rejected before any student is known, so not logged
    assert [r[0] for r in rows("SELECT event FROM login_events ORDER BY id")] == ["login", "logout"]
    assert rows("SELECT email FROM students") == [("kid@gmail.com",)]


def test_denied_logged(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("ALLOWED_DOMAINS", "school.org")
    c = TestClient(create_app(verify=fake_verify))
    assert login(c).status_code == 403
    assert rows("SELECT event, email FROM login_events") == [("denied", "kid@gmail.com")]


def test_session_expires_after_window(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SESSION_SECRET", "x" * 40)
    now = [1_000_000.0]
    monkeypatch.setattr("server.app.time.time", lambda: now[0])
    c = TestClient(create_app(verify=fake_verify), follow_redirects=False)
    login(c)
    now[0] += 24 * 3600 - 60
    assert c.get("/api/me").status_code == 200
    now[0] += 120
    assert c.get("/api/me").status_code == 401
    assert c.get("/").status_code == 303
    login(c)
    assert c.get("/api/me").status_code == 200


def test_schema_isolated(client):
    login(client)
    tables = rows("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('students','progress','login_events')")
    assert tables == []


def test_first_login_collects_profile(client):
    login(client)
    me = client.get("/api/me").json()
    assert me["profileComplete"] is False
    for page in ["/", "/chapter-01-force.html"]:
        r = client.get(page)
        assert (r.status_code, r.headers["location"]) == (303, "/profile.html")
    assert client.get("/profile.html").status_code == 200
    r = complete_profile(client, "  Asha   Rao ", "")
    assert r.status_code == 200 and r.json()["fullName"] == "Asha Rao" and r.json()["profileComplete"] is True
    assert client.get("/").status_code == 200
    # Profile persists across sessions.
    client.post("/api/logout")
    login(client)
    assert client.get("/api/me").json()["name"] == "Asha Rao"
    assert client.get("/").status_code == 200


def test_profile_validation(client):
    assert client.put("/api/profile", json={"fullName": "Asha"}).status_code == 401
    assert client.get("/profile.html").status_code == 303
    login(client)
    for bad in [{"fullName": ""}, {"fullName": "A"}, {"fullName": "x" * 81}, {"fullName": "Asha", "school": "s" * 101}, []]:
        assert client.put("/api/profile", json=bad).status_code == 422
    assert client.get("/api/me").json()["profileComplete"] is False


def test_streak_math():
    d = lambda n: date(2026, 10, n)
    assert streaks([], d(20)) == (0, 0)
    assert streaks([d(18), d(19), d(20)], d(20)) == (3, 3)
    assert streaks([d(18), d(19)], d(20)) == (2, 2)  # yesterday still counts
    assert streaks([d(10), d(11), d(12), d(18)], d(20)) == (0, 3)  # broken, best kept
    assert streaks([d(20), d(20)], d(20)) == (1, 1)


def test_streak_and_badges(monkeypatch, client):
    day = 86400
    now = [1_792_000_000.0]
    monkeypatch.setattr("server.app.time.time", lambda: now[0])
    login(client)
    complete_profile(client)
    badges = lambda: {b["id"]: b["earned"] for b in client.get("/api/streak").json()["badges"]}
    assert client.get("/api/streak").json()["current"] == 0 and not badges()["first-steps"]
    client.get("/")  # dashboard visit is not a study day
    assert client.get("/api/streak").json()["current"] == 0
    for _ in range(3):
        login(client)  # sessions last 24h, so a daily visitor signs in each day
        assert client.get("/chapter-01-force.html").status_code == 200
        client.get("/chapter-01-force.html")  # same day twice counts once
        now[0] += day
    login(client)
    st = client.get("/api/streak").json()
    assert (st["current"], st["longest"]) == (3, 3)
    assert badges()["first-steps"] and badges()["streak-3"] and not badges()["streak-7"] and not badges()["chapter-done"]
    client.put("/api/progress", json={"done": [1]})
    assert badges()["chapter-done"]
    now[0] += 3 * day  # miss days: current resets, best stays
    login(client)
    st = client.get("/api/streak").json()
    assert (st["current"], st["longest"]) == (0, 3) and badges()["streak-3"]


def test_streak_requires_login(client):
    assert client.get("/api/streak").status_code == 401


def test_theme_script_public(client):
    r = client.get("/theme.js")
    assert r.status_code == 200 and "data-theme" in r.text


PW = "class-secret-123"


def pw_login(c, email="Kid@Example.com", password=PW):
    return c.post("/api/auth/password", json={"email": email, "password": password})


def test_password_login_disabled_by_default(client):
    assert client.get("/api/config").json()["passwordLogin"] is False
    assert pw_login(client).status_code == 404


def test_password_login(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_PASSWORD", PW)
    c = TestClient(create_app(verify=fake_verify), follow_redirects=False)
    assert c.get("/api/config").json()["passwordLogin"] is True
    assert pw_login(c, password="nope").status_code == 401
    assert pw_login(c, email="not-an-email").status_code == 422
    r = pw_login(c)
    assert r.status_code == 200 and r.json()["profileComplete"] is False
    assert c.get("/").headers["location"] == "/profile.html"
    complete_profile(c)
    assert c.get("/").status_code == 200
    assert c.get("/api/me").json()["email"] == "kid@example.com"
    c.put("/api/progress", json={"done": [1]})
    c.post("/api/logout")
    pw_login(c, email="KID@example.com")  # email is case-insensitive: same student
    assert c.get("/api/progress").json() == {"done": [1]}
    events = rows("SELECT event, method FROM login_events ORDER BY id")
    assert ("denied", "password") in events and ("login", "password") in events


def test_password_login_respects_allowlist(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_PASSWORD", PW)
    monkeypatch.setenv("ALLOWED_DOMAINS", "school.org")
    c = TestClient(create_app(verify=fake_verify))
    assert pw_login(c).status_code == 403
    assert pw_login(c, email="a@school.org").status_code == 200


def test_password_login_rate_limited(client, monkeypatch):
    monkeypatch.setenv("DEFAULT_PASSWORD", PW)
    c = TestClient(create_app(verify=fake_verify))
    for _ in range(10):
        assert pw_login(c, password="wrong").status_code == 401
    assert pw_login(c, password="wrong").status_code == 429
    assert pw_login(c).status_code == 429  # even the right password waits out the lockout


def test_migrations_idempotent_and_versioned():
    from server.migrate import run_migrations

    run_migrations()
    run_migrations()  # running again changes nothing
    assert rows("SELECT version_num FROM alembic_version") == [("0001",)]
    tables = {r[0] for r in rows("SELECT table_name FROM information_schema.tables WHERE table_schema = 'icse_physics_test'")}
    assert {"students", "login_events", "study_days", "progress", "alembic_version"} <= tables


def test_migration_adopts_existing_unversioned_schema():
    """A database created by the old startup code (tables, no alembic_version) is adopted without data loss."""
    from server.migrate import run_migrations

    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
        conn.execute(f"CREATE TABLE {TEST_SCHEMA}.students (sub TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), last_login TIMESTAMPTZ NOT NULL DEFAULT now())")
        conn.execute(f"INSERT INTO {TEST_SCHEMA}.students (sub, email, name) VALUES ('old', 'old@x.org', 'Old')")
    run_migrations()
    assert rows("SELECT sub, full_name FROM students") == [("old", None)]
    assert rows("SELECT version_num FROM alembic_version") == [("0001",)]
