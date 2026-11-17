"""Trailer YouTube video ids, so the app can play trailers in its own player.

Watchmode's trailer link is used when it has one; otherwise KinoCheck (free, no
key) is asked by IMDb id. Results, including "no trailer", are cached for days.
"""

import re
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.core.cache import cache

from .movie_source import MovieSourceUnavailable, _fetch_json

KINOCHECK_URL = 'https://api.kinocheck.com/movies'
TRAILER_CACHE_SECONDS = 60 * 60 * 24 * 7
YOUTUBE_ID = re.compile(r'[A-Za-z0-9_-]{11}')


def youtube_id(url):
    """The video id of a YouTube watch, short or embed link, else None."""
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower().removeprefix('www.').removeprefix('m.')
    candidate = None
    if host == 'youtu.be':
        candidate = parsed.path.lstrip('/').split('/')[0]
    elif host in ('youtube.com', 'youtube-nocookie.com'):
        if parsed.path == '/watch':
            candidate = (parse_qs(parsed.query).get('v') or [None])[0]
        elif parsed.path.startswith(('/embed/', '/shorts/')):
            candidate = parsed.path.split('/')[2]
    return candidate if candidate and YOUTUBE_ID.fullmatch(candidate) else None


def _kinocheck_trailer(film_id):
    data = _fetch_json(
        f'{KINOCHECK_URL}?{urlencode({"imdb_id": film_id, "language": "en"})}',
        # KinoCheck refuses Python's default User-Agent with 403.
        {'Accept': 'application/json', 'User-Agent': 'FilmSage/1.0'},
        settings.RAPIDAPI_TIMEOUT_SECONDS,
    )
    if not isinstance(data, dict):
        return None
    candidates = [data.get('trailer')] + list(data.get('videos') or [])
    for video in candidates:
        if isinstance(video, dict):
            video_id = video.get('youtube_video_id')
            if isinstance(video_id, str) and YOUTUBE_ID.fullmatch(video_id):
                return video_id
    return None


def trailer_youtube_id(film_id, watchmode_url=None):
    direct = youtube_id(watchmode_url)
    if direct:
        return direct
    key = f'trailer:youtube:{film_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    if not settings.KINOCHECK_ENABLED:
        return None
    try:
        video_id = _kinocheck_trailer(film_id)
    except MovieSourceUnavailable:
        # Not cached: a KinoCheck outage should not hide trailers for a week.
        return None
    cache.set(key, video_id or '', TRAILER_CACHE_SECONDS)
    return video_id
