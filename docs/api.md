# API reference

Audited 2026-11-16 from `config/urls.py` and each app's `urls.py` / views. Base path:
`/api/`. Unless marked **public**, every endpoint needs `Authorization: Token <key>`
(DRF `TokenAuthentication`, default permission `IsAuthenticated`).

Errors from the new endpoints go through `config/exceptions.py` and look like
`{"code": "<machine_code>", "detail": "<human message>"}`. Legacy endpoints (`/api/film/`,
`/api/review/`, `/api/account/login|register`) return
`{"message": …, "feature": …, "status": …}`.

"App" says whether the Flutter client calls it today.

## Accounts — `/api/account/`

| Method | Path | Auth | App | Purpose |
|---|---|---|---|---|
| POST | `register` | public | yes | Body `{username, email, password}` → `{token, message, status}` |
| POST | `login` | public | yes | Body `{email, password}` → `{token, user, message, status}` |
| GET, PATCH | `profile` | token | yes | Own profile (`id, username, email, balance, bio, avatar, cover, equipped_frame, …`). PATCH multipart `bio`, `avatar`, `cover`, `equipped_frame` (errors `invalid_frame`, `frame_locked`) |
| GET | `users/<id>` | token | yes | Public profile `{id, username, bio, avatar, cover, equipped_frame}` |

## Lists — `/api/lists/` (current)

| Method | Path | App | Purpose |
|---|---|---|---|
| GET | `` | yes | Counts per list |
| GET, POST | `top5/` | yes | Paginated Top 5; POST adds a film to a slot |
| PATCH, DELETE | `top5/<film_id>/` | yes | Move slot / remove |
| GET, POST | `watched/` | yes | Paginated watched list / add |
| DELETE | `watched/<film_id>/` | yes | Remove |
| GET, POST | `watchlist/` | yes | Paginated watchlist / add |
| DELETE | `watchlist/<film_id>/` | yes | Remove |

## Lists — `/api/film/` (legacy, still used by Home)

`get_top_5_movies`, `get_wathced_list_movies`, `get_watch_list_movies`,
`get_popular_friends_list_movies` (GET) and `add_top_5_movies`, `add_watched_movies`,
`add_watchlist_movies`, `delete_top_5_movies`, `delete_wathced_list_movies`,
`delete_watch_list_movies` (POST, body `{imdbid}`). Typos are part of the contract.
Retire after the app moves to `/api/lists/`.

## Catalog — `/api/films/`

| Method | Path | App | Purpose |
|---|---|---|---|
| GET | `search?q=&page=` | yes | Search via RapidAPI online-movie-database, fallback OMDb. Errors `query_too_short`, `movie_source_not_configured`, `movie_source_unavailable` |
| GET | `<film_id>/` | yes | Film detail (cached in the `Film` table) with where-to-watch providers |
| GET | `<film_id>/stills/` | yes | Still images |
| GET | `popular/` | yes | Popular this week (by FilmSage activity) |

## Takes — `/api/takes/`

| Method | Path | App | Purpose |
|---|---|---|---|
| GET | `films/<film_id>/summary/` | yes | Reaction counts and summary for a film |
| PUT | `films/<film_id>/reaction/` | yes | Set own reaction |
| GET, POST | `films/<film_id>/takes/` | yes | List / create takes on a film |
| GET | `films/<film_id>/friends/` | yes | Friends' activity on a film |
| POST | `topics/` | yes | Create a discussion, question, poll, scene or spoiler post |
| GET | `topics/trending/` | yes | Trending topics |
| GET | `explore/` | yes | Explore feed |
| GET | `friends/takes/` | yes | Takes by friends |
| GET | `me/takes/` | yes | Own takes |
| PUT | `takes/<id>/votes/<kind>/` | yes | Like / dislike a take |
| GET, POST | `takes/<id>/comments/` | yes | Comments (threaded via `parent`, with `stance`) |
| POST | `takes/<id>/poll/` | yes | Vote in a poll |
| PUT | `comments/<id>/votes/<kind>/` | yes | Vote on a comment |
| GET | `leaderboard/` | yes | Reputation leaderboard |
| POST | `translate/` | yes | Translate text through OpenRouter (disabled without a key) |

## Social — `/api/social/`

| Method | Path | App | Purpose |
|---|---|---|---|
| GET | `users/search?q=` | yes | Find users |
| GET | `me/connections` | yes | Friends and pending requests |
| POST | `friend-requests` | yes | Send a request |
| POST | `friend-requests/<id>/accept`, `/decline`, `/cancel` | yes | Respond |
| POST | `movie-suggestions` | yes | Suggest a film to one or more friends |
| GET | `notifications` | yes | Notifications |
| POST | `notifications/read` | yes | Mark all read |

## Content

| Method | Path | Auth | App | Purpose |
|---|---|---|---|---|
| GET | `/api/articles/` | public | yes | Published staff articles plus imdb232 movie news (cached 30 min) |
| GET | `/api/upcoming/` | public | yes | Published upcoming films |
| GET | `/api/review/get_review` | public | no (legacy) | Old reviews |
| POST | `/api/review/add_review` | token | no (legacy) | Old reviews |
| GET | `/articles/<slug>/`, `/articles/<slug>/body/` | public | web | Article HTML pages |
| GET | `/`, `/join/` | public | web | Landing page |

## Called by the app but missing here

| Path | Called from |
|---|---|
| `/api/debates/invites/`, `/api/debates/<id>/`, `/api/debates/<id>/questions/` | `lib/features/debate/data/api_debate_repository.dart` |
| Points / balance endpoint | `FakePointsGateway` placeholder in the app |
