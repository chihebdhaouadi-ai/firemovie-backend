# FilmSage — backend

Django REST API for FilmSage, a social film app. It owns accounts, film lists (Top 5,
watched, watchlist), takes (reviews, discussions, polls, scene and spoiler posts),
reactions, comments, votes, reputation (levels, badges, avatar frames), friends,
notifications, staff articles and upcoming films. It also proxies every third-party movie
API so keys never reach the app.

Flutter client: [firemovie](https://github.com/chihebdhaouadi-ai/firemovie).

## Stack

Python 3.12 (3.11 works locally), Django 5.2, Django REST Framework 3.18 with token auth,
PostgreSQL in production (SQLite locally), WhiteNoise for static files, optional S3
(Heroku Bucketeer) for uploaded media, gunicorn on Heroku.

## Quick start

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in what you need; all keys are optional locally
venv/bin/python manage.py migrate
venv/bin/python manage.py createsuperuser
venv/bin/python manage.py runserver 127.0.0.1:8000
```

- API: `http://127.0.0.1:8000/api/…` (see [docs/api.md](docs/api.md))
- Admin: `http://127.0.0.1:8000/admin/` (articles, upcoming films, users)
- Landing page: `http://127.0.0.1:8000/`

Without `RAPIDAPI_KEY` / `OMDB_API_KEY`, film search and detail return a
`*_not_configured` error. Without `IMDB232_RAPIDAPI_KEY` the news feed is empty. Without
`OPENROUTER_API_KEY` translation is disabled.

## Environment

All configuration comes from environment variables, documented in
[.env.example](.env.example). Never commit `.env`. Production must set
`DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`
(set by Heroku Postgres) and, for media, the `BUCKETEER_*` variables.

## Checks

```bash
venv/bin/python manage.py check
venv/bin/python manage.py makemigrations --check --dry-run
venv/bin/python manage.py test
```

CI runs all three on pushes and pull requests (`.github/workflows/tests.yml`).

## Deploy

Heroku app `filwise` (`git push heroku <branch>:main`). The `release` phase in the
`Procfile` runs migrations. A `Dockerfile` is also provided.

## Docs

- [docs/architecture.md](docs/architecture.md): apps, data model, integrations, security
- [docs/api.md](docs/api.md): every endpoint
- [docs/tech-debt.md](docs/tech-debt.md): known problems and missing pieces
- [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md): workflow for people and AI agents

## License

MIT, see [LICENSE](LICENSE).
