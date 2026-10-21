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

Early stage. The repo is plain static files with no build system, package manager, linter or test suite, so there are no build/lint/test commands yet. Existing files:

- `chapter-01-force.html`: Chapter 1 lesson.
- `chapter-04-refraction-plane-surfaces.html`: Chapter 4 lesson (replaces the old `bending-light.html` simulator).
- `index.html`: student dashboard listing all 12 chapters. When a chapter is finished, set its `href` in the `CHAPTERS` array there.
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

### Accessibility and usability
- Interactive controls must be keyboard-operable and have visible focus; do not rely on colour alone to convey meaning.
- Must work on a phone, since students will often use one. Touch targets at least 44px.

## Authentication and student access (planned)

Students log in with Google (Gmail) and only then see the chapter list and lessons. This is not implemented yet; the backend has not been chosen. Before building it, confirm the choice with the user (candidates: Firebase Authentication with Google provider, or Google Identity Services plus a small backend).

Rules whenever this is built:
- Use Google Sign-In (OAuth/OIDC) only; never collect or store passwords.
- Access control must be enforced server-side (or by the auth provider's rules), not just by hiding UI in client JS. Static HTML in a public repo or public URL is readable by anyone, so decide where gated chapter content is served from before assuming login protects it.
- Verify Google ID tokens on the server. Never trust an email or name sent from the client.
- Store the minimum student data needed (Google ID/email, name, progress). These are minors: avoid unnecessary personal data, no third-party trackers or ads, and keep a note of what is stored.
- No secrets, API keys with write access, or service-account files in the repo. Public client IDs are fine; keep everything else in environment variables or the hosting provider's secret store.
- Plan for progress tracking (chapters completed, quiz scores) keyed to the signed-in user, and a sign-out control on every page.
- Restricting access to an allowlist of emails or a school domain is a possible requirement; ask before assuming open sign-in for any Google account.

## Working in this repo

- Ask before large structural decisions (framework, hosting, auth provider). Until decided, keep chapters as plain static HTML so they stay portable.
- Do not rewrite or restyle existing chapters unless asked; make targeted edits.
- Commit only when asked. Commit messages: short imperative summary, e.g. "Add Chapter 2 Work, Energy and Power".
