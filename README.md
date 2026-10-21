# ICSE Class 10 Physics, Interactive

An interactive version of the ICSE Class 10 Physics book. Students sign in with their Google (Gmail) account, see a dashboard of all 12 chapters, and learn with simulations and worked examples. The dashboard tracks progress, study streaks and badges.

Chapters available so far: **1. Force** and **4. Refraction of Light at Plane Surfaces**. The rest are added over time.

## What is in the repo

| Path | Purpose |
|---|---|
| `index.html` | Student dashboard: chapters, progress, streak, badges |
| `chapter-NN-*.html` | One self-contained lesson per chapter |
| `login.html`, `profile.html` | Google sign-in and first-login details (name, school) |
| `theme.js` | Light / Dark switch shown on every page |
| `server/app.py` | FastAPI server: sign-in, page protection, progress, streaks |
| `tests/` | Server tests |
| `scripts/audit_a11y.py` | Accessibility and phone-layout check |
| `railway.json` | Start command for deploying on Railway |
| `CLAUDE.md` | Project conventions (read before adding a chapter) |

## Run it locally

### Quick look, no setup

Open `index.html` in a browser. The dashboard and chapters work, with no sign-in. Progress is saved in that browser only.

### Full app (sign-in, saved progress, streaks)

**You need**
- [uv](https://docs.astral.sh/uv/) (installs Python and the dependencies for you)
- PostgreSQL running locally
- A Google OAuth client ID (type "Web application")

**1. Start Postgres and check it**

```
pg_isready
```

It should say "accepting connections". The app creates its own schema (`icse_physics`) and tables on first start, so it does not touch other tables in the same database.

**2. Create your `.env`**

```
cp .env.example .env
```

Then fill it in:

| Variable | What to put |
|---|---|
| `GOOGLE_CLIENT_ID` | Your OAuth client ID from Google Cloud Console |
| `SESSION_SECRET` | A long random string: `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | For example `postgresql://localhost/railway` |
| `DB_SCHEMA` | `icse_physics` (default) |
| `SESSION_HOURS` | `24` (students sign in again after this long) |
| `COOKIE_SECURE` | `0` locally, `1` when served over HTTPS |
| `DEFAULT_PASSWORD` | Optional shared class password. Students then sign in with email + this password on the login page. Empty turns it off |
| `ALLOWED_EMAILS`, `ALLOWED_DOMAINS` | Optional. Leave empty to allow any Google account |
| `STUDY_TIMEZONE` | Optional. Defaults to `Asia/Kolkata`. Decides when a study day starts and ends |

`.env` is ignored by git. Never commit it.

**3. Allow localhost in Google Cloud Console**

Open your OAuth client and add `http://localhost:8000` under **Authorized JavaScript origins**. Changes can take a few minutes to apply. Sign-in fails until this is done.

**4. Start the server**

```
uv run --env-file .env uvicorn server.app:create_app --factory --port 8000
```

**5. Open the app**

Go to **http://localhost:8000** (use `localhost`, not `127.0.0.1`; Google treats them as different origins).

First visit: sign in with Google, give your name on the profile page, then you land on the dashboard.

## Tests

The server tests use a throwaway Postgres schema (`icse_physics_test`) that they create and drop. They need the same local Postgres.

```
uv run pytest -q
```

Run them before pushing any change to `server/`, `tests/` or `pyproject.toml`.

## Accessibility and phone check

Run this on any new or changed page. It checks 375px and 1280px widths in light and dark, and expects no violations and no sideways scrolling.

```
uv run --no-project --with playwright --with axe-playwright-python python scripts/audit_a11y.py
```

If Playwright's browser is not installed, set `CHROMIUM_PATH` to a Chromium binary.

## Deploy

The server runs on any host that runs Python and has Postgres (the repo includes a `railway.json` for Railway). On the host:

1. Set the same variables as in `.env`, with `DATABASE_URL` pointing at the host's Postgres and `COOKIE_SECURE=1`.
2. Add the site's public address to **Authorized JavaScript origins** in Google Cloud Console.

GitHub Pages can show the static dashboard in guest mode, but it cannot run the server, so sign-in does not work there.

## Adding a chapter

1. Create `chapter-NN-short-title.html` as one self-contained file, following `CLAUDE.md` (physics checked against the ICSE syllabus, both themes, `theme.js` included).
2. Set its `href` in the `CHAPTERS` list in `index.html`.
3. Run the accessibility check.

## Notes for maintainers

- The repo is public, so chapter source is readable on GitHub. The sign-in protects the pages the server serves, not the source files.
- Student data kept: Google ID, email, name, school, progress, study days and login events. Students are minors, so do not add trackers or collect more than this.
