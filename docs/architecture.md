# Backend architecture

Audited 2026-11-16 on branch `feature/find-film`. Update when apps, models, integrations or
settings change.

## Django apps

| App | Responsibility |
|---|---|
| `config` | Settings, root URLs, unified API exception handler, WSGI/ASGI |
| `accounts` | Custom `User` (balance, bio, avatar, cover, equipped_frame), register/login/profile, admin with progression |
| `films` | `Film` cache of external metadata, `FilmEntry` lists (top5, watched, watchlist), catalog search/detail/stills/popular via `movie_source.py`; legacy `/api/film/` endpoints |
| `takes` | Reactions, takes (review, discussion, question, poll, scene, spoiler), votes, polls, threaded comments with stance, comment votes, reputation (`reputation.py`: XP, levels, badges, frames), leaderboard, translation (`translation.py`) |
| `social` | Follows, friend requests, movie suggestions, notifications |
| `articles` | Staff-written articles (admin) and imdb232 movie news (`news_source.py`), API list and HTML pages |
| `upcoming` | Staff-entered upcoming films (admin) |
| `reviews` | Legacy reviews, not used by the current app |
| `landing` | Marketing landing page and `/join/` redirect to the web app |

## Data model

```
User ─┬─< FilmEntry (film_id, list_type, slot_index)        unique per user/list/film, slot per user
      ├─< FilmReaction (film_id, reaction)                   unique per user/film
      ├─< Take (film_id, reaction, tag, body, image, spoiler, scene, timecode)
      │      ├─< TakeVote (kind)            unique per user/take
      │      ├─< PollOption ─< PollVote     one vote per user/take
      │      └─< TakeComment (body, stance, parent → TakeComment)
      │             └─< TakeCommentVote     unique per user/comment
      ├─< Follow (follower, following)
      ├─< FriendRequest (sender, receiver, status)
      ├─< MovieSuggestion (sender, recipient, film_* snapshot, comment)
      ├─< Notification (recipient, actor, kind, friend_request?, suggestion?, read)
      └─< Review (legacy)
Film (imdb_id, title, year, overview, runtime, genres, director, poster_url, rating, fetched_at)
Article (title, slug, cover, body, published, published_at)
UpcomingFilm (title, poster, release_date, description, published)
```

Films are referenced by IMDb id string (`tt…`), not by foreign key, so lists and takes work
before a film is cached.

## Authentication and authorization

- DRF `TokenAuthentication`; tokens are created on register/login and never expire.
- Default permission `IsAuthenticated`. Public (`AllowAny`): register, login,
  `/api/articles/`, `/api/upcoming/`, legacy `get_review`.
- Ownership checks live in the views/services (users only change their own lists, votes,
  comments, profile).
- Django admin for staff content and user progression.

## External integrations

| Service | Used for | Setting | Code |
|---|---|---|---|
| RapidAPI online-movie-database | Search, details, where to watch, stills | `RAPIDAPI_KEY` | `films/movie_source.py` |
| OMDb | Detail fallback | `OMDB_API_KEY` | `films/movie_source.py` |
| RapidAPI imdb232 | Movie news feed; person pages | `IMDB232_RAPIDAPI_KEY` | `articles/news_source.py`, `films/people.py` |
| OpenRouter | Translation of takes and comments | `OPENROUTER_API_KEY`, `OPENROUTER_TRANSLATE_MODEL` | `takes/translation.py` |
| Heroku Postgres | Database | `DATABASE_URL` | `dj_database_url` |
| Bucketeer (S3) | Uploaded media | `BUCKETEER_*` | `django-storages` |

All outbound calls use `urllib` with timeouts and are cached in Django's cache.

**Reddit:** there is no Reddit integration or synchronization in this codebase.

## Background work

None. There is no Celery, cron, scheduler or management command. External data is fetched
on request and cached in `LocMemCache` (per process; with 2 gunicorn workers each has its
own cache).

## Security review (2026-11-16)

| Finding | Severity | Notes |
|---|---|---|
| No rate limiting on login, register, translate | High | Brute force; translate spends paid OpenRouter credit |
| `DJANGO_DEBUG` defaults to `True` when unset | High | A misconfigured deploy runs in debug; production must set it |
| Tokens never expire, no logout/revoke endpoint | Medium | |
| `CORS_ALLOW_ALL_ORIGINS = True` | Low | Token auth (no cookies) limits the impact |
| `ALLOWED_HOSTS='*'` in debug | Low | Debug only |
| Login loops over every user with the email | Low | Email is not unique on `User` |
| Upload validation (avatar, cover, take images) | Check | Confirm size and content-type limits |
| Leaked client token in the Flutter repo history | High | Rotate token `2aa9f4…` in admin |

`manage.py check --deploy` with debug settings reports the 6 expected debug warnings; run it
with production variables before releasing.
