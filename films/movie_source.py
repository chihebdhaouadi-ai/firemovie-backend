import hashlib
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException

IMDB_ID_PATTERN = re.compile(r'tt\d{1,10}')
SEARCH_LIMIT = 10


class MovieSourceNotConfigured(APIException):
    status_code = 503
    default_code = 'movie_source_not_configured'
    default_detail = 'Film search is not configured on the server.'


class MovieSourceUnavailable(APIException):
    status_code = 502
    default_code = 'movie_source_unavailable'
    default_detail = 'Film data is temporarily unavailable. Try again.'


class FilmNotFound(APIException):
    status_code = 404
    default_code = 'film_not_found'
    default_detail = 'No film matches this id.'


def _get(path, params):
    if not settings.RAPIDAPI_KEY:
        raise MovieSourceNotConfigured()
    url = f'https://{settings.RAPIDAPI_HOST}{path}?{urlencode(params)}'
    request = Request(url, headers={
        'X-RapidAPI-Key': settings.RAPIDAPI_KEY,
        'X-RapidAPI-Host': settings.RAPIDAPI_HOST,
    })
    try:
        with urlopen(request, timeout=settings.RAPIDAPI_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise MovieSourceUnavailable() from exc
    except (OSError, ValueError) as exc:
        raise MovieSourceUnavailable() from exc


def _cache_key(prefix, raw):
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'movie:{prefix}:{digest}'


def _imdb_id(value):
    match = IMDB_ID_PATTERN.search(value or '')
    return match.group(0) if match else None


def _is_movie(row):
    return row.get('titleType') == 'movie' and _imdb_id(row.get('id')) is not None


def _summary(row):
    return {
        'film_id': _imdb_id(row.get('id')),
        'title': row.get('title') or '',
        'year': row.get('year'),
        'poster_url': (row.get('image') or {}).get('url'),
    }


def _director(credits):
    directors = (credits.get('crew') or {}).get('director') or []
    return directors[0].get('name') if directors else None


def search_movies(query, page):
    key = _cache_key('search', f'{page}:{query.lower()}')
    cached = cache.get(key)
    if cached is not None:
        return cached
    if page == 1:
        data = _get('/title/v2/find', {
            'title': query,
            'limit': SEARCH_LIMIT,
            'sortArg': 'moviemeter,asc',
        }) or {}
        results = [_summary(row) for row in data.get('results', []) if _is_movie(row)]
    else:
        results = []
    payload = {
        'page': page,
        'total_pages': 1,
        'total_results': len(results),
        'results': results,
    }
    cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return payload


def movie_detail(film_id):
    key = _cache_key('detail', film_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    overview = _get('/title/get-overview-details', {'tconst': film_id}) or {}
    title = overview.get('title')
    if not isinstance(title, dict):
        raise FilmNotFound()
    credits = _get('/title/get-full-credits', {'tconst': film_id}) or {}

    payload = {
        'film_id': film_id,
        'title': title.get('title') or '',
        'year': title.get('year'),
        'overview': (
            (overview.get('plotSummary') or overview.get('plotOutline') or {}).get('text') or ''
        ),
        'runtime': title.get('runningTimeInMinutes'),
        'genres': [genre for genre in overview.get('genres') or [] if isinstance(genre, str)],
        'director': _director(credits),
        'poster_url': (title.get('image') or {}).get('url'),
        'rating': (overview.get('ratings') or {}).get('rating'),
    }
    cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return payload
