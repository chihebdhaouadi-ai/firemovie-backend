import hashlib
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException


class TmdbNotConfigured(APIException):
    status_code = 503
    default_code = 'tmdb_not_configured'
    default_detail = 'Film search is not configured on the server.'


class TmdbUnavailable(APIException):
    status_code = 502
    default_code = 'tmdb_unavailable'
    default_detail = 'Film data is temporarily unavailable. Try again.'


class FilmNotFound(APIException):
    status_code = 404
    default_code = 'film_not_found'
    default_detail = 'No film matches this id.'


def _get(path, params):
    if not settings.TMDB_API_KEY:
        raise TmdbNotConfigured()
    query = urlencode({**params, 'api_key': settings.TMDB_API_KEY})
    url = f'{settings.TMDB_API_BASE_URL}{path}?{query}'
    try:
        with urlopen(url, timeout=settings.TMDB_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise TmdbUnavailable() from exc
    except (OSError, ValueError) as exc:
        raise TmdbUnavailable() from exc


def _cache_key(prefix, raw):
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f'tmdb:{prefix}:{digest}'


def _image_url(path):
    return f'{settings.TMDB_IMAGE_BASE_URL}{path}' if path else None


def _year(release_date):
    return int(release_date[:4]) if release_date and release_date[:4].isdigit() else None


def _summary(item):
    return {
        'film_id': str(item['id']),
        'title': item.get('title') or '',
        'year': _year(item.get('release_date')),
        'poster_url': _image_url(item.get('poster_path')),
    }


def _providers(data):
    region = (data.get('watch/providers') or {}).get('results', {}).get(settings.TMDB_REGION, {})

    def named(kind):
        return [
            {'name': row['provider_name'], 'logo_url': _image_url(row.get('logo_path'))}
            for row in region.get(kind, [])
        ]

    return {
        'link': region.get('link'),
        'flatrate': named('flatrate'),
        'rent': named('rent'),
        'buy': named('buy'),
    }


def search_movies(query, page):
    key = _cache_key('search', f'{page}:{query.lower()}')
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _get('/search/movie', {'query': query, 'page': page, 'include_adult': 'false'}) or {}
    payload = {
        'page': data.get('page', page),
        'total_pages': data.get('total_pages', 0),
        'total_results': data.get('total_results', 0),
        'results': [_summary(item) for item in data.get('results', [])],
    }
    cache.set(key, payload, settings.TMDB_CACHE_SECONDS)
    return payload


def movie_detail(film_id):
    key = _cache_key('detail', film_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    tmdb_id = film_id
    if film_id.startswith('tt'):
        found = _get(f'/find/{film_id}', {'external_source': 'imdb_id'}) or {}
        matches = found.get('movie_results') or []
        if not matches:
            raise FilmNotFound()
        tmdb_id = str(matches[0]['id'])

    data = _get(f'/movie/{tmdb_id}', {'append_to_response': 'watch/providers'})
    if data is None:
        raise FilmNotFound()

    payload = {
        'film_id': film_id,
        'tmdb_id': str(data['id']),
        'imdb_id': data.get('imdb_id'),
        'title': data.get('title') or '',
        'year': _year(data.get('release_date')),
        'overview': data.get('overview') or '',
        'runtime': data.get('runtime'),
        'genres': [genre['name'] for genre in data.get('genres', [])],
        'poster_url': _image_url(data.get('poster_path')),
        'backdrop_url': _image_url(data.get('backdrop_path')),
        'vote_average': data.get('vote_average'),
        'watch_providers': _providers(data),
    }
    cache.set(key, payload, settings.TMDB_CACHE_SECONDS)
    return payload
