import os

import psycopg
import pytest
from fastapi.testclient import TestClient

from server.app import create_app

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
    for name in ["CLAUDE.md", ".env", "pyproject.toml", "server", "chapter-01-force.html.bak"]:
        assert client.get(f"/{name}").status_code == 404
    assert client.get("/%2e%2e/etc/passwd").status_code == 404


def test_login_flow_and_pages(client):
    r = login(client)
    assert r.status_code == 200 and r.json()["email"] == "kid@gmail.com"
    assert client.get("/api/me").json()["name"] == "Kid One"
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
