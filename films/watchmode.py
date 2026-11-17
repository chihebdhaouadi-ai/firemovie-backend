"""Browse lists from Watchmode: most popular films, films by release year,
films on one streaming service, and the list of streaming services.

Watchmode list results carry IMDb ids but no posters, so posters come from the
Film table when the film is stored, otherwise from OMDb (cached).
"""

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

from .models import Film
from .movie_source import (
    IMDB_ID_PATTERN,
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    _cache_key,
    _fetch_json,
    _omdb_get,
    _poster,
)

WATCHMODE_URL = 'https://api.watchmode.com/v1'
PAGE_SIZE = 20
SERVICES_LIMIT = 30
POSTER_CACHE_SECONDS = 60 * 60 * 24 * 30
SERVICES_CACHE_SECONDS = 60 * 60 * 24
# Watchmode genres that only apply to TV or adult titles; left out of film browsing.
NON_FILM_GENRE_IDS = {21, 22, 23, 25, 26, 28, 30, 34, 35, 36, 37, 38, 39, 40, 41}
LOOKUP_WORKERS = 8


def _watchmode_get(path, params):
    key = settings.WATCHMODE_API_KEY
    if not key:
        raise MovieSourceNotConfigured()
    data = _fetch_json(
        f'{WATCHMODE_URL}{path}?{urlencode(params)}',
        {'X-API-Key': key, 'Accept': 'application/json'},
        settings.RAPIDAPI_TIMEOUT_SECONDS,
    )
    # Watchmode reports errors (bad key, quota) as {"success": false, ...}.
    if data is None or (isinstance(data, dict) and data.get('success') is False):
        raise MovieSourceUnavailable()
    return data


def _region():
    return settings.STREAMING_COUNTRY.upper()


def _omdb_poster(film_id):
    key = f'omdb:poster:{film_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        data = _omdb_get({'i': film_id})
    except (MovieSourceNotConfigured, MovieSourceUnavailable):
        # A missing poster is not worth failing the whole list; try again later.
        return None
    poster = _poster(data.get('Poster')) if isinstance(data, dict) else None
    cache.set(key, poster or '', POSTER_CACHE_SECONDS)
    return poster


def _posters(film_ids):
    stored = dict(
        Film.objects.filter(imdb_id__in=film_ids)
        .exclude(poster_url='')
        .values_list('imdb_id', 'poster_url')
    )
    missing = [film_id for film_id in film_ids if not stored.get(film_id)]
    with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
        stored.update(zip(missing, pool.map(_omdb_poster, missing)))
    return stored


def _summaries(rows):
    rows = [
        row for row in rows
        if isinstance(row, dict)
        and IMDB_ID_PATTERN.fullmatch(row.get('imdb_id') or '') is not None
    ]
    posters = _posters([row['imdb_id'] for row in rows])
    return [
        {
            'film_id': row['imdb_id'],
            'title': row.get('title') or '',
            'year': row.get('year') if isinstance(row.get('year'), int) else None,
            'poster_url': posters.get(row['imdb_id']),
        }
        for row in rows
    ]


def discover_movies(page, year=None, provider_id=None, genre_id=None, language=None, country=None):
    """One page of films, most popular first. Optional filters: release [year],
    one subscription service, one Watchmode genre, original [language]
    (ISO 639-1), and [country] where the film is streaming (ISO 3166-1)."""
    params = {
        'types': 'movie',
        'sort_by': 'popularity_desc',
        'page': page,
        'limit': PAGE_SIZE,
    }
    if year is not None:
        params['release_date_start'] = f'{year}0101'
        params['release_date_end'] = f'{year}1231'
    if genre_id is not None:
        params['genres'] = genre_id
    if language is not None:
        params['languages'] = language
    if country is not None:
        params['regions'] = country
    if provider_id is not None:
        params['source_ids'] = provider_id
        params.setdefault('regions', _region())

    key = _cache_key('watchmode-titles', urlencode(sorted(params.items())))
    cached = cache.get(key)
    if cached is not None:
        return cached

    data = _watchmode_get('/list-titles/', params)
    rows = data.get('titles') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise MovieSourceUnavailable()
    try:
        total_pages = max(1, int(data.get('total_pages') or 1))
        total_results = max(0, int(data.get('total_results') or 0))
    except (TypeError, ValueError):
        raise MovieSourceUnavailable()
    payload = {
        'page': page,
        'total_pages': total_pages,
        'total_results': total_results,
        'results': _summaries(rows),
    }
    cache.set(key, payload, settings.RAPIDAPI_CACHE_SECONDS)
    return payload


def streaming_providers():
    """Subscription streaming services in the configured country."""
    region = _region()
    key = f'watchmode:services:{region}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    rows = _watchmode_get('/sources/', {'regions': region, 'types': 'sub'})
    if not isinstance(rows, list):
        raise MovieSourceUnavailable()
    payload = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), int):
            continue
        name = row.get('name')
        if not name or name in seen:
            continue
        seen.add(name)
        logo = row.get('logo_100px')
        payload.append({
            'id': row['id'],
            'name': name,
            'logo_url': logo if isinstance(logo, str) and logo.startswith('https://') else None,
        })
        if len(payload) == SERVICES_LIMIT:
            break
    cache.set(key, payload, SERVICES_CACHE_SECONDS)
    return payload


def film_genres():
    """Watchmode genres that apply to films, alphabetical."""
    key = 'watchmode:genres'
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = _watchmode_get('/genres/', {})
    if not isinstance(rows, list):
        raise MovieSourceUnavailable()
    payload = sorted(
        (
            {'id': row['id'], 'name': row['name']}
            for row in rows
            if isinstance(row, dict) and isinstance(row.get('id'), int)
            and row.get('name') and row['id'] not in NON_FILM_GENRE_IDS
        ),
        key=lambda row: row['name'],
    )
    cache.set(key, payload, SERVICES_CACHE_SECONDS)
    return payload


def streaming_countries():
    """Countries the Watchmode plan can filter by (where a film is streaming)."""
    key = 'watchmode:countries'
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = _watchmode_get('/regions/', {})
    if not isinstance(rows, list):
        raise MovieSourceUnavailable()
    payload = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('plan_enabled'):
            continue
        code = row.get('country')
        if not isinstance(code, str) or len(code) != 2 or not row.get('name'):
            continue
        flag = row.get('flag')
        payload.append({
            'code': code.upper(),
            'name': row['name'],
            'flag_url': flag if isinstance(flag, str) and flag.startswith('https://') else None,
        })
    cache.set(key, payload, SERVICES_CACHE_SECONDS)
    return payload


EXTRAS_CACHE_SECONDS = 60 * 60 * 24 * 3
CAST_LIMIT = 20
CREW_LIMIT = 12
# Crew roles worth showing on a film page, most important first.
CREW_ROLES = (
    'Director', 'Screenplay', 'Writer', 'Story', 'Novel', 'Characters', 'Producer',
    'Original Music Composer', 'Director of Photography', 'Editor',
)
# Order of the where-to-watch groups.
SOURCE_TYPES = ('sub', 'free', 'tve', 'rent', 'buy')


def _source_logos():
    """Logo per Watchmode source id, for every source type in the configured country."""
    region = _region()
    key = f'watchmode:source-logos:{region}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = _watchmode_get('/sources/', {'regions': region})
    logos = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get('id'), int):
                logo = row.get('logo_100px')
                if isinstance(logo, str) and logo.startswith('https://'):
                    logos[row['id']] = logo
    cache.set(key, logos, SERVICES_CACHE_SECONDS)
    return logos


def _cast(people):
    cast = sorted(
        (p for p in people if p.get('type') == 'Cast' and p.get('full_name')),
        key=lambda p: p.get('order') if isinstance(p.get('order'), int) else 1_000_000,
    )
    return [
        {'name': p['full_name'], 'role': p.get('role') or '', 'person_id': _person_id(p)}
        for p in cast[:CAST_LIMIT]
    ]


def _crew(people):
    """Key crew, one entry per person. Watchmode packs several roles into one
    comma-separated field ("Director, Producer, Screenplay")."""
    rank = {role: index for index, role in enumerate(CREW_ROLES)}
    jobs = {}
    ids = {}
    for p in people:
        if p.get('type') != 'Crew' or not p.get('full_name'):
            continue
        ids.setdefault(p['full_name'], _person_id(p))
        roles = [r.strip() for r in str(p.get('role') or '').split(',')]
        for role in roles:
            if role in rank and role not in jobs.setdefault(p['full_name'], []):
                jobs[p['full_name']].append(role)
    picked = sorted(
        ((name, sorted(roles, key=rank.get)) for name, roles in jobs.items() if roles),
        key=lambda item: (rank[item[1][0]], item[0]),
    )
    return [
        {'name': name, 'job': ', '.join(roles), 'person_id': ids.get(name)}
        for name, roles in picked[:CREW_LIMIT]
    ]


def _person_id(person):
    value = person.get('person_id')
    return value if isinstance(value, int) and value > 0 else None


def person_imdb_id(person_id):
    """IMDb name id (nm...) for a Watchmode person id. One Watchmode credit when
    not cached; cached for 30 days."""
    key = f'watchmode:person-imdb:{person_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    data = _watchmode_get(f'/person/{person_id}/', {})
    imdb_id = data.get('imdb_id') if isinstance(data, dict) else None
    imdb_id = imdb_id if isinstance(imdb_id, str) and imdb_id.startswith('nm') else ''
    cache.set(key, imdb_id, 60 * 60 * 24 * 30)
    return imdb_id or None


def _sources(rows):
    try:
        logos = _source_logos()
    except (MovieSourceNotConfigured, MovieSourceUnavailable):
        logos = {}
    sources, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        kind, name, url = row.get('type'), row.get('name'), row.get('web_url')
        if kind not in SOURCE_TYPES or not name or not isinstance(url, str) \
                or not url.startswith('https://') or (kind, name) in seen:
            continue
        seen.add((kind, name))
        price = row.get('price')
        sources.append({
            'name': name,
            'type': kind,
            'url': url,
            'logo_url': logos.get(row.get('source_id')),
            'price': price if isinstance(price, (int, float)) else None,
        })
    sources.sort(key=lambda s: SOURCE_TYPES.index(s['type']))
    return sources


def title_extras(film_id):
    """Trailer, main cast, key crew and where to watch (configured country) for one
    film. Costs 4 Watchmode credits when not cached, so it is cached for days."""
    key = f'watchmode:extras:v2:{_region()}:{film_id}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _watchmode_get(
        f'/title/{film_id}/details/',
        {'append_to_response': 'sources,cast-crew', 'regions': _region()},
    )
    if not isinstance(data, dict):
        raise MovieSourceUnavailable()
    people = [p for p in (data.get('cast') or data.get('cast_crew') or []) if isinstance(p, dict)]
    trailer = data.get('trailer')
    backdrop = data.get('backdrop')
    payload = {
        'backdrop_url': backdrop if isinstance(backdrop, str) and backdrop.startswith('https://') else None,
        'trailer_url': trailer if isinstance(trailer, str) and trailer.startswith('https://') else None,
        'cast': _cast(people),
        'crew': _crew(people),
        'sources': _sources(data.get('sources') or []),
    }
    cache.set(key, payload, EXTRAS_CACHE_SECONDS)
    return payload
