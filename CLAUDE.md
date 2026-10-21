# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project purpose

An interactive, web-based version of the **ICSE Class 10 Physics textbook**. Each chapter is a self-contained interactive lesson (explanations, simulations, visual explainers, worked examples, practice questions). Students sign in with their **Google (Gmail) account** and then open chapters to learn.

Audience: ICSE Grade 10 students (about 14-16 years old). Write at that level: short sentences, concrete everyday examples, no unexplained jargon. Follow the ICSE Class 10 Physics syllabus (CISCE) and its chapter order:

1. Force
2. Work, Energy and Power
3. Machines
4. Refraction of Light at Plane Surfaces
5. Refraction through Lens
6. Spectrum
7. Sound
8. Current Electricity
9. Electrical Power and Household Circuits
10. Electromagnetism
11. Calorimetry
12. Radioactivity

Check chapter numbers/titles against the syllabus before naming a file; do not invent chapters.

## Current state

Chapters are plain static HTML. A small FastAPI server (`server/app.py`) adds Google sign-in, gated pages and per-student progress (Postgres). Python is managed with `uv`.

Commands:
- Needs a local Postgres (same one as `ai_workspace/gr-proposal`, `postgresql://localhost/railway`). Tables live in their own schema `icse_physics`, created automatically at startup; tests use a throwaway `icse_physics_test` schema.
- Run tests: `uv run pytest -q` (single test: `uv run pytest tests/test_app.py::test_progress`)
- Run locally: `uv run --env-file .env uvicorn server.app:create_app --factory --port 8000` (copy `.env.example` to `.env` first)

Existing files:

- `chapter-01-force.html`: Chapter 1 lesson.
- `chapter-04-refraction-plane-surfaces.html`: Chapter 4 lesson (replaces the old `bending-light.html` simulator).
- `index.html`: student dashboard listing all 12 chapters. When a chapter is finished, set its `href` in the `CHAPTERS` array there.
- `login.html`: Google sign-in page (public). `profile.html`: first-login details (full name, optional school).
- `server/app.py`, `tests/test_app.py`, `pyproject.toml`, `.env.example`: server, tests, config.
- `theme.js`: shared Light/Dark switch (served publicly by the server).
- `scripts/audit_a11y.py`: accessibility/phone audit (see Conventions).
- `README.md`: placeholder.

Update this section whenever tooling, directory layout or the auth backend is added (including how to run a single test, if tests are added).

## Conventions

### Files and structure
- One chapter = one self-contained HTML file named `chapter-NN-short-title.html` (lowercase, hyphens, two-digit number). Inline CSS and JS; keep it a single file unless it needs supporting files. This is required for publishing with the Artifact tool.
- Load external scripts/styles only from approved CDNs (cdnjs.cloudflare.com preferred, cdn.jsdelivr.net/npm, unpkg.com) and fonts from Google Fonts. No other external dependencies.
- Follow the visual style already used in the existing chapters (design tokens as CSS variables on `:root`, light and dark themes, mobile-friendly layout with 16px gutters, no horizontal page scroll). Read an existing chapter before starting a new one and reuse its patterns instead of inventing new ones.
- Suggested chapter flow: learning goals, concept explanation, interactive simulation(s), worked numericals, quick-check questions, summary/key formulae.

### Physics and content correctness
- Physics must be correct and use ICSE-style notation, SI units and formulae as taught at this level. Recompute every numeric example and answer; state units and significant figures.
- Use standard ICSE sign conventions and ray-diagram conventions (e.g. Cartesian sign convention for lenses/mirrors where the syllabus uses it).
- Keep terminology identical to the ICSE textbook (e.g. "angle of incidence", "critical angle", "moment of a force") so students can map the app to their book and exams.
- Practice questions should mirror ICSE exam style (short answer, numericals, reasoning) and include worked answers.
- Simulations must not be misleading: label approximations (e.g. ideal conditions, ignored friction) clearly.

### Light/dark theme
- Every page includes `<script src="theme.js"></script>` at the end of `<head>`. It adds a Light/Dark switch at the top right and remembers the student's choice (localStorage `icse10-theme`); with no choice saved the page follows the device setting.
- Pages must define colour tokens on bare `:root` (light), then redefine them under `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){...}}` and `:root[data-theme="dark"]{...}`, and style everything through the tokens. Use the token names `--bg --panel --fg --line --accent` so the switch matches the page.

### Accessibility and usability
- Run `scripts/audit_a11y.py` on every new or changed page. Target: zero axe violations, no horizontal scroll at 375px, controls at least 44px, one `<main>` landmark, `lang` on `<html>`, scrollable regions focusable and labelled.
- Interactive controls must be keyboard-operable and have visible focus; do not rely on colour alone to convey meaning.
- Must work on a phone, since students will often use one. Touch targets at least 44px.

## Authentication and student access

Implemented in `server/app.py`: Google Identity Services on `login.html` sends an ID token to `POST /api/auth/google`; the server verifies it (signature, expiry, audience, `email_verified`) and sets a signed, HttpOnly session cookie. `/` and `chapter-NN-*.html` redirect to `/login.html` without a session. Only allowlisted filenames are served, never arbitrary paths. `GET/PUT /api/progress` stores completed chapters per student. On first sign-in the student is redirected to `profile.html` to give a full name and optional school; gated pages stay locked until `profile_completed_at` is set. Collect no more than this (minors). Study streaks and badges: opening a `chapter-*.html` page records a study day (`study_days`, `STUDY_TIMEZONE`, default Asia/Kolkata); badges are computed in `server/app.py` (`BADGES`) and shown on the dashboard. Sessions expire a fixed `SESSION_HOURS` (default 24) after sign-in, enforced server-side. Logins, logouts and denied attempts are recorded in `login_events`. `index.html` falls back to guest mode (localStorage) when `/api/me` is absent, e.g. on GitHub Pages.

- OAuth client: reuses the `GOOGLE_CLIENT_ID` from the sibling `ai_workspace/gr-proposal` project (copied into the gitignored `.env`; the client secret is not needed for ID-token sign-in and was not copied). Each new site origin (localhost, production URL) must be added to that client's Authorized JavaScript origins in Google Cloud Console.
- `ALLOWED_EMAILS` / `ALLOWED_DOMAINS` restrict who may sign in; empty means any Google account.
- Never commit `.env`, secrets, or service-account files. Besides Google, the server supports one shared class password (`DEFAULT_PASSWORD` env var, off when empty): `POST /api/auth/password` takes email + that password, is rate limited (10 wrong tries per IP per 15 min), and creates a separate `pw:<email>` student. The password lives only in `.env` / host variables, never in the repo. Do not add per-student passwords or store password hashes without asking. Keep stored student data minimal (Google ID, email, name, progress); students are minors, so no trackers.
- The GitHub repo is public, so chapter source is readable by anyone. The login gate protects the served site, not the repo contents.

## Working in this repo

- Ask before large structural decisions (framework, hosting, auth provider). Until decided, keep chapters as plain static HTML so they stay portable.
- Do not rewrite or restyle existing chapters unless asked; make targeted edits.
- Tests: if a change touches server-side code (`server/`, `tests/`, `pyproject.toml`, or DB/auth behaviour), run `uv run pytest -q` before pushing, and only then. Do not run tests on every edit, and skip them for changes limited to static HTML/docs. Never push with failing tests.
- Commit only when asked. Commit messages: short imperative summary, e.g. "Add Chapter 2 Work, Energy and Power".
