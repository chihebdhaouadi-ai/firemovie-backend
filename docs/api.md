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
| GET | `<film_id>/` | yes | Film detail (cached in the `Film` table) plus `trailer_youtube_id` (Watchmode trailer, else KinoCheck by IMDb id, cached 7 days), `trailer_url`, `cast` (`name`, `role`), `crew` (`name`, `job`) and `watch_providers.available` (`name`, `type` sub/free/tve/rent/buy, `url`, `logo_url`, `price`) from Watchmode, cached 3 days (4 credits per uncached film). Falls back to the RapidAPI lookup for providers when Watchmode has none |
| GET | `<film_id>/stills/` | yes | Still images |
| GET | `popular/` | yes | Popular this week (by FilmSage activity) |
| GET | `browse/?page=&year=&provider=&genre=&language=&country=` | yes | Most popular films from Watchmode (posters from OMDb), optionally by release year and/or streaming service (subscription, `STREAMING_COUNTRY`). Same shape as `search`. Errors `invalid_browse_filter`, `movie_source_not_configured` (no `WATCHMODE_API_KEY`) |
| GET | `providers/` | yes | Subscription streaming services in `STREAMING_COUNTRY` (`id`, `name`, `logo_url`) for `browse/?provider=` |
| GET | `genres/` | yes | Film genres (`id`, `name`) for `browse/?genre=` |
| GET | `countries/` | yes | Countries the Watchmode plan covers (`code`, `name`, `flag_url`) for `browse/?country=` (films streaming there) |

## Takes — `/api/takes/`

| Method | Path | App | Purpose |
|---|---|---|---|
| GET | `films/<film_id>/summary/` | yes | Reaction counts per feeling, `total` people, `my_reactions` (pick order; `my_reaction` = first, for older clients), most felt, positive percentages (people, by their leaning) |
| PUT | `films/<film_id>/reaction/` | yes | Set own feelings: `{"reactions": [...]}` up to 3, replaces the set, `[]` clears; older `{"reaction": x|null}` still works. Error `invalid_reaction` |
| GET, POST | `films/<film_id>/takes/` | yes | List / create takes on a film (body up to 1500 characters; `author_frame` is the author's equipped frame). Each take has `reaction` (the first feeling, stored on the take) and `author_reactions` (the author's current feelings, up to 3, pick order). Optional `skin` (`normal` default, `electric_thunder`) sets the card background others see. Optional `spoiler` (bool, default false) tells apps to blur the take until the reader taps |
| GET | `films/<film_id>/friends/` | yes | Friends' activity on a film (one row per feeling; `user` includes `equipped_frame`) |
| POST | `topics/` | yes | Create a discussion, question, poll, scene or spoiler post (optional `skin`, as above) |
| GET | `topics/trending/` | yes | Trending topics |
| GET | `top/?tag=` | yes | Top 100 takes of all time by replies (x2) and votes, optionally one tag (`review`, `question`, `discussion`, `hot_take`, `poll`, `scene`). Error `invalid_tag` |
| GET | `explore/` | yes | Explore feed |
| GET | `friends/takes/` | yes | Takes by friends |
| GET | `friends/stories/` | yes | Friends' takes and comments from the last 7 days as story groups: `[{user, latest_at, items: [{kind: take\|comment, id, take_id, tag, body, spoiler, film, created_at}]}]`, newest friend first, items oldest first (max 10 per friend) |
| GET | `me/takes/` | yes | Own takes |
| GET, PATCH, DELETE | `takes/<id>/` | yes | One take shaped like a feed item (with `film`). Author only: `PATCH {"body", "skin"?, "spoiler"?}` edits (sets `edited: true`; topics stay ≤ 280), `DELETE` removes. Error `not_owner` (403) |
| POST | `takes/<id>/report/` | yes | Report a take: `{"reason": "spam"|"harassment"|"hate"|"spoiler"|"other", "details"?}`. 201 first time, 200 when updating your report. Error `own_take` |
| POST | `takes/<id>/share/` | yes | Send a take to friends: `{"recipient_ids": [...], "message"?}` (≤ 20). Each gets a `take_shared` notification. Error `not_friends` |
| PUT | `takes/<id>/votes/<kind>/` | yes | `{"active": bool}`. Reviews take one of `up` / `draw` / `down`; questions and discussions take one of `like` / `dislike`. Voting again with another kind replaces the reader's vote. A top-level review comment with stance `changed_my_mind` also votes `up`, and `disagree_but_fair` votes `draw` |
| GET, POST | `takes/<id>/comments/` | yes | Comments (threaded via `parent`, with `stance`). `@username` tags a friend, who gets a `take_mention` notification |
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
| GET | `notifications` | yes | Notifications. `take_shared` / `take_mention` carry `take` (`id`, `film_id`, `tag`, `body`), `comment_id` and `message` |
| POST | `notifications/read` | yes | Mark all read |

## Messaging — `/api/messaging/`

Chats between friends: `direct` (one-to-one), `group`, and `topic` (a private
group around a subject). Only friends can be messaged or added. Clients poll
for new messages; there is no push yet.

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `conversations/` | yes | The user's chats, most recently active first: `[{id, kind, title, members, last_message, unread, updated_at}]`. A direct chat's `title` is the other person's username |
| POST | `conversations/` | yes | `{kind: "direct", user_id}` opens (or reuses) the chat with a friend. `{kind: "group"\|"topic", title, member_ids}` creates one. Errors `not_friends`, `title_required`, `self_chat` |
| GET | `conversations/<id>/messages/?after=<message id>` | yes | Oldest first; the newest 100, or only those after `after`. Marks the chat read. 404 for non-members |
| POST | `conversations/<id>/messages/` | yes | `{body}` (max 2000). Error `empty_message` |

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
