# AGENTS.md — instructions for AI coding agents

Applies to Claude Code, Codex, Cursor and any other agent working in this repository.
Humans should follow it too.

## Project

FilmSage Django REST backend. Flutter client: `chihebdhaouadi-ai/firemovie`.
Read first: `README.md`, `docs/architecture.md`, `docs/api.md`, `docs/tech-debt.md`.

## Source of truth

- **GitHub** owns code, issues, pull requests, development status and releases.
- **Notion (FilmSage HQ)** owns product specs, design docs and progress reports. Do not track
  tasks in Notion; link issues and PRs from it.

## Workflow (required)

1. Start from a GitHub issue (create one with a template if none exists).
2. Branch from `main`: `feature/<issue#>-…`, `fix/<issue#>-…`, `chore/<issue#>-…`.
   Never commit to `main` directly.
3. Keep changes scoped to the issue. No unrelated refactors.
4. Before every commit:
   ```bash
   venv/bin/python manage.py check
   venv/bin/python manage.py makemigrations --check --dry-run
   venv/bin/python manage.py test
   ```
   All tests must pass (baseline: 240 passing).
5. Open a PR with the template and `Closes #<issue>`. CI must be green.
6. Update `docs/api.md` for any endpoint change, `docs/architecture.md` for models,
   settings or integrations, and `CHANGELOG.md` (Unreleased).

## Rules

- Never commit `.env`, `db.sqlite3`, `media/`, keys, tokens or credentials. Read settings
  from environment variables with a safe default and document them in `.env.example`.
- Never break the app's contract silently. If an endpoint, field or error code changes,
  link the matching Flutter PR or keep the old shape.
- Legacy endpoints (`/api/film/…`, `/api/review/…`) stay until the app stops calling them.
- Every outbound HTTP call needs a timeout, caching where sensible, and a clear
  `*_not_configured` error when its key is missing. Tests must mock outbound calls.
- Include migrations with model changes; never edit an applied migration.
- Ask the owner before destructive operations: deleting data or apps, force-pushing,
  rewriting history, or deploying to Heroku.
- Never claim something works without running it.

## Conventions

- One Django app per domain (`accounts`, `films`, `takes`, `social`, `articles`, `upcoming`).
- Business logic in `services.py` / helper modules, thin views, DRF serializers for input.
- Errors: raise `APIException` subclasses with a stable `default_code`; the handler in
  `config/exceptions.py` renders `{code, detail}`.
- Tests live in each app's `tests.py` / `test_*.py`.
