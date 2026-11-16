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
STREAMING_HOST = 'streaming-availability.p.rapidapi.com'
OMDB_URL = 'https://www.omdbapi.com/'


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


def _omdb_get(params):
    if not settings.OMDB_API_KEY:
        raise MovieSourceNotConfigured()
    return _fetch_json(
        f'{OMDB_URL}?{urlencode({"apikey": settings.OMDB_API_KEY, **params})}',
        {},
        settings.RAPIDAPI_TIMEOUT_SECONDS,
    )


def _cache_key(prefix, raw):
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'movie:{prefix}:{digest}'


def _is_movie(row):
    return (
        row.get('Type') == 'movie'
        and IMDB_ID_PATTERN.fullmatch(row.get('imdbID') or '') is not None
    )


def _summary(row):
    return {
        'film_id': row['imdbID'],
        'title': row.get('Title') or '',
        'year': _year(row.get('Year')),
        'poster_url': _poster(row.get('Poster')),
    }


def _year(value):
    match = re.match(r'\s*(\d{4})', str(value or ''))
    return int(match.group(1)) if match else None


def _poster(value):
    return value if isinstance(value, str) and value != 'N/A' else None


def _omdb_error(data):
    if not isinstance(data, dict):
        raise MovieSourceUnavailable()
    if data.get('Response') == 'False':
        return data.get('Error') or 'Unknown OMDb error'
    return None


def _omdb_not_found(data):
    error = _omdb_error(data)
    if error is None:
        return False
    if isinstance(error, str) and error.lower().startswith('movie not found'):
        return True
    raise MovieSourceUnavailable()


def search_movies(query, page):
    key = _cache_key('search', f'{page}:{query.lower()}')
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _omdb_get({'s': query, 'page': page})
    if data is None or _omdb_not_found(data):
        total_results = 0
        total_pages = 1
        results = []
    else:
        raw_results = data.get('Search') or []
        if not isinstance(raw_results, list):
            raise MovieSourceUnavailable()
        try:
            total_results = int(data.get('totalResults', 0))
        except (TypeError, ValueError):
            raise MovieSourceUnavailable()
        if total_results < 0:
            raise MovieSourceUnavailable()
        total_pages = max(1, (total_results + SEARCH_LIMIT - 1) // SEARCH_LIMIT)
        results = [_summary(row) for row in raw_results if isinstance(row, dict) and _is_movie(row)]
    payload = {
        'page': page,
        'total_pages': total_pages,
        'total_results': total_results,
        'results': results,
    }
    cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return payload


def fetch_film_detail(film_id):
    detail = _omdb_get({'i': film_id, 'plot': 'full'})
    if detail is None or _omdb_not_found(detail):
        raise FilmNotFound()
    title = detail.get('Title')
    if not title:
        raise FilmNotFound()

    return {
        'film_id': film_id,
        'title': title,
        'year': _year(detail.get('Year')),
        'overview': '' if detail.get('Plot') in (None, 'N/A') else detail.get('Plot'),
        'runtime': _runtime(detail.get('Runtime')),
        'genres': _genres(detail.get('Genre')),
        'director': _first(detail.get('Director')),
        'poster_url': _poster(detail.get('Poster')),
        'rating': _float(detail.get('imdbRating')),
    }


def _runtime(value):
    match = re.match(r'\s*(\d+)', str(value or ''))
    return int(match.group(1)) if match else None


def _genres(value):
    if not isinstance(value, str) or value == 'N/A':
        return []
    return [genre.strip() for genre in value.split(',') if genre.strip()]


def _first(value):
    if not isinstance(value, str) or value == 'N/A':
        return None
    return value.split(',', 1)[0].strip() or None


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _watch_sources(film_id):
    key = _cache_key('streaming', film_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    show = _rapidapi_get(
        STREAMING_HOST,
        f'/shows/{film_id}',
        {'country': settings.STREAMING_COUNTRY},
    ) or {}
    options = (show.get('streamingOptions') or {}).get(settings.STREAMING_COUNTRY) or []
    cache.set(key, options, settings.RAPIDAPI_CACHE_SECONDS)
    return options


def _https(value):
    return value if isinstance(value, str) and value.startswith('https://') else None


def watch_providers(film_id):
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
        service = option.get('service') or {}
        service_id = service.get('id')
        name = service.get('name')
        url = _https(option.get('link'))
        if not service_id or not name or not url or service_id in seen:
            continue
        seen.add(service_id)
        images = service.get('imageSet') or {}
        logo = _https(images.get('darkThemeImage')) or _https(images.get('lightThemeImage'))
        available.append({'name': name, 'logo_url': logo, 'url': url})
    return {'link': None, 'available': available}


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
