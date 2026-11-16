"""Person details for the app's cast and crew pages, from IMDb232 (RapidAPI).

Two IMDb232 calls per uncached person: `actors/get-overview` (photo, height, bio,
birth and death) and `actors/get-known-for` (the titles the person is best known
for, with the credit they had). The combined result is cached for 30 days.
"""

import re
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException

from .movie_source import (
    IMDB_ID_PATTERN,
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    _fetch_json,
)

PEOPLE_HOST = 'imdb232.p.rapidapi.com'
OVERVIEW_PATH = '/api/actors/get-overview'
KNOWN_FOR_PATH = '/api/actors/get-known-for'
PERSON_ID_PATTERN = re.compile(r'nm\d{1,10}')
PERSON_CACHE_SECONDS = 60 * 60 * 24 * 30
KNOWN_FOR_LIMIT = 20
# Only films open in the app's film detail screen, so TV titles are left out.
FILM_TITLE_TYPES = {'movie'}


class PersonNotFound(APIException):
    status_code = 404
    default_code = 'person_not_found'
    default_detail = 'No person matches this id.'


def _imdb232_get(path, person_id):
    if not settings.IMDB232_RAPIDAPI_KEY:
        raise MovieSourceNotConfigured()
    data = _fetch_json(
        f'https://{PEOPLE_HOST}{path}?{urlencode({"nm": person_id})}',
        {
            'x-rapidapi-key': settings.IMDB232_RAPIDAPI_KEY,
            'x-rapidapi-host': PEOPLE_HOST,
        },
        settings.RAPIDAPI_TIMEOUT_SECONDS,
    )
    if data is None:
        return None
    if not isinstance(data, dict):
        raise MovieSourceUnavailable()
    name = (data.get('data') or {}).get('name')
    return name if isinstance(name, dict) else None


def _https(value):
    return value if isinstance(value, str) and value.startswith('https://') else None


def _text(node, *path):
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if not isinstance(node, str):
        return None
    return node.strip() or None


def _height(node):
    if not isinstance(node, dict):
        return None
    measurement = node.get('measurement') or {}
    value = measurement.get('value')
    centimeters = value if measurement.get('unit') == 'CENTIMETER' \
        and isinstance(value, (int, float)) and value > 0 else None
    display = _text(node, 'displayableProperty', 'value', 'plainText')
    if centimeters is None and display is None:
        return None
    return {
        'cm': round(centimeters) if centimeters is not None else None,
        'display': display,
    }


def _date(node):
    value = node.get('date') if isinstance(node, dict) else None
    return value if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else None


def _known_for(name):
    edges = ((name or {}).get('knownFor') or {}).get('edges') or []
    if not isinstance(edges, list):
        return []
    films, seen = [], set()
    for edge in edges:
        node = (edge or {}).get('node') if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue
        title = node.get('title') or {}
        film_id = title.get('id')
        if not isinstance(film_id, str) or IMDB_ID_PATTERN.fullmatch(film_id) is None \
                or film_id in seen:
            continue
        if ((title.get('titleType') or {}).get('id')) not in FILM_TITLE_TYPES:
            continue
        name_text = _text(title, 'titleText', 'text')
        if name_text is None:
            continue
        seen.add(film_id)
        credit = node.get('credit') or {}
        year = (title.get('releaseYear') or {}).get('year')
        characters = [
            c['name'].strip()
            for c in (credit.get('characters') or [])
            if isinstance(c, dict) and isinstance(c.get('name'), str) and c['name'].strip()
        ]
        films.append({
            'film_id': film_id,
            'title': name_text,
            'year': year if isinstance(year, int) else None,
            'poster_url': _https((title.get('primaryImage') or {}).get('url')),
            'credit_type': 'cast' if credit.get('__typename') == 'Cast' else 'crew',
            'job': _text(credit, 'category', 'text'),
            'characters': characters,
        })
    return films[:KNOWN_FOR_LIMIT]


def person_detail(person_id):
    """Photo, height, biography, birth/death and known-for films for one IMDb
    name id (`nm…`). Raises PersonNotFound when IMDb has no such person."""
    if PERSON_ID_PATTERN.fullmatch(person_id or '') is None:
        raise PersonNotFound()
    key = f'people:imdb232:{person_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    overview = _imdb232_get(OVERVIEW_PATH, person_id)
    name = _text(overview, 'nameText', 'text')
    if name is None:
        raise PersonNotFound()
    known_for = _imdb232_get(KNOWN_FOR_PATH, person_id)

    payload = {
        'person_id': person_id,
        'name': name,
        'photo_url': _https((overview.get('primaryImage') or {}).get('url')),
        'height': _height(overview.get('height')),
        'biography': _text(overview, 'bio', 'text', 'plainText'),
        'birth_date': _date(overview.get('birthDate')),
        'birth_place': _text(overview, 'birthLocation', 'text'),
        'death_date': _date(overview.get('deathDate')),
        'known_for': _known_for(known_for),
    }
    cache.set(key, payload, PERSON_CACHE_SECONDS)
    return payload
