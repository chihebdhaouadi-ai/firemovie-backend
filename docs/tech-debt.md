# Known bugs, missing pieces and technical debt — backend

Audited 2026-11-16. Each item should have a GitHub issue; link it here when it exists.

## Missing features the app expects

- Debates API (`/api/debates/invites/`, `/api/debates/<id>/`, `/api/debates/<id>/questions/`).
- Points API: `User.balance` exists, nothing exposes or changes it.
- Social sign-in (Google, Apple, Reddit). No Reddit integration of any kind.

## Security

See the table in `docs/architecture.md`. Highest priority: rate limiting, safe `DEBUG`
default, rotating the leaked token.

## Code health

- Legacy endpoints in `films/urls.py` (with typos) and the whole `reviews` app are kept for
  old clients. Remove once the app uses `/api/lists/` and takes.
- `LocMemCache` is per process; use Redis or the database cache in production so caches and
  rate limits are shared.
- No background jobs: news and film data are fetched during requests.
- No API schema (OpenAPI). Consider `drf-spectacular`.
- Local Python is 3.11 (venv) while `.python-version`, CI and Docker use 3.12.

## Tests

240 tests, all passing (2026-11-16). Gaps: no tests for `landing`, upload validation,
throttling, or production settings.
