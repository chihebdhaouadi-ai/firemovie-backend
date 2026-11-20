# Changelog

All notable changes to the FilmSage backend. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org).

## [Unreleased]

### Added
- `POST /api/social/notifications/<id>/read` marks one of your notifications read.
- Movie list comments take replies (`parent_id`) and an optional photo (`image`,
  multipart; JPEG/PNG/WebP up to 5 MB). Each comment now returns `parent_id`,
  `image_url`, `is_writer` and `is_mine`. Migration `movielists.0003`.

### Changed
- `PUT /api/movie-lists/<id>/like/` now accepts a heart on your own list.

### Fixed
- A friend request notification no longer sends `friend_request_id` once the
  request is answered, so the app stops offering Accept on accepted requests.
- Messaging app (`/api/messaging/`): direct chats between friends, groups and
  private topics, with unread counts.
- `GET /api/takes/friends/stories/`: friends' takes and comments from the last week
  as story groups.
- Project documentation: README, AGENTS.md, CONTRIBUTING.md, `docs/` (architecture, API,
  tech debt).
- GitHub issue and pull request templates; CI runs on pushes and pull requests.
- Movie news source (imdb232) for the articles feed.
- Comment stance, take tags, poll / scene / spoiler takes (migrations 0007 and 0008).

## [0.1.0] — baseline

First tracked state of the API, as published on `main` before this changelog existed.
