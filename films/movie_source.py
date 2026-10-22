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
STILLS_LIMIT = 10
STREAMING_HOST = 'ott-details.p.rapidapi.com'
STREAMING_PLATFORM_NAMES = {
    'amazon': 'Amazon Video',
    'directv': 'DIRECTV',
    'hoopla': 'Hoopla',
    'itunes': 'Apple TV',
    'play': 'Google Play',
    'redbox': 'Redbox',
    'tubitv': 'Tubi',
    'vudu': 'Vudu',
    'youtube': 'YouTube',
}


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


def _fetch_json(url, headers, timeout):
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise MovieSourceUnavailable() from exc
    except (OSError, ValueError) as exc:
        raise MovieSourceUnavailable() from exc


def _rapidapi_get(host, path, params):
    if not settings.RAPIDAPI_KEY:
        raise MovieSourceNotConfigured()
    url = f'https://{host}{path}?{urlencode(params)}'
    return _fetch_json(url, {
        'X-RapidAPI-Key': settings.RAPIDAPI_KEY,
        'X-RapidAPI-Host': host,
    }, settings.RAPIDAPI_TIMEOUT_SECONDS)


def _get(path, params):
    return _rapidapi_get(settings.RAPIDAPI_HOST, path, params)


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


def _detail_payload(film_id):
    overview = _get('/title/get-overview-details', {'tconst': film_id}) or {}
    title = overview.get('title')
    if not isinstance(title, dict):
        raise FilmNotFound()
    credits = _get('/title/get-full-credits', {'tconst': film_id}) or {}

    return {
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


def _watch_sources(film_id):
    key = _cache_key('streaming', film_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    title = _rapidapi_get(STREAMING_HOST, '/gettitleDetails', {'imdbid': film_id}) or {}
    countries = (title.get('streamingAvailability') or {}).get('country') or {}
    options = countries.get(settings.STREAMING_COUNTRY.upper()) or []
    cache.set(key, options, settings.RAPIDAPI_CACHE_SECONDS)
    return options


def _watch_providers(film_id):
    empty = {'link': None, 'available': []}
    if not settings.RAPIDAPI_KEY:
        return empty
    try:
        options = _watch_sources(film_id)
    except MovieSourceUnavailable:
        return empty

    available = []
    seen = set()
    for option in options:
        platform = (option.get('platform') or '').strip().lower()
        if not platform:
            continue
        name = STREAMING_PLATFORM_NAMES.get(platform, platform.title())
        if name in seen:
            continue
        seen.add(name)
        available.append({'name': name, 'logo_url': None})
    return {'link': None, 'available': available}


def movie_detail(film_id):
    key = _cache_key('detail', film_id)
    payload = cache.get(key)
    if payload is None:
        payload = _detail_payload(film_id)
        cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return {**payload, 'watch_providers': _watch_providers(film_id)}


def film_stills(film_id):
    key = _cache_key('stills', film_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    data = _get('/title/get-images', {'tconst': film_id}) or {}
    stills = [
        image['url']
        for image in data.get('images') or []
        if image.get('type') == 'still_frame'
        and image.get('url')
        and (image.get('width') or 0) >= (image.get('height') or 0)
    ][:STILLS_LIMIT]

    payload = {'film_id': film_id, 'stills': stills}
    cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return payload
