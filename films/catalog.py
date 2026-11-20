from .models import Film
from .movie_source import (
    IMDB_ID_PATTERN,
    FilmNotFound,
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    fetch_film_detail,
    watch_providers,
)
from .trailers import trailer_youtube_id
from .watchmode import title_extras

STORED_FIELDS = ('title', 'year', 'overview', 'runtime', 'genres', 'director', 'poster_url', 'rating')


def stored_film(film_id):
    film = Film.objects.filter(imdb_id=film_id).first()
    if film is None:
        detail = fetch_film_detail(film_id)
        film, _ = Film.objects.update_or_create(
            imdb_id=film_id,
            defaults={field: detail[field] for field in STORED_FIELDS},
        )
    return film


def try_stored_film(film_id):
    if not IMDB_ID_PATTERN.fullmatch(film_id or ''):
        return None
    try:
        return stored_film(film_id)
    except (FilmNotFound, MovieSourceNotConfigured, MovieSourceUnavailable):
        return None


EMPTY_EXTRAS = {'backdrop_url': None, 'trailer_url': None, 'cast': [], 'crew': [], 'sources': None}


def film_backdrop_stills(film_id):
    """Stills fallback: the Watchmode backdrop, when there is one."""
    backdrop = _extras(film_id).get('backdrop_url')
    return {'film_id': film_id, 'stills': [backdrop] if backdrop else []}


def _extras(film_id):
    # Extras are nice to have; the film page still opens without them.
    try:
        return title_extras(film_id)
    except (FilmNotFound, MovieSourceNotConfigured, MovieSourceUnavailable):
        return EMPTY_EXTRAS


def film_detail(film_id):
    film = stored_film(film_id)
    extras = _extras(film_id)
    sources = extras['sources']
    video_id = trailer_youtube_id(film_id, extras['trailer_url'])
    return {
        'film_id': film.imdb_id,
        **{field: getattr(film, field) for field in STORED_FIELDS},
        # The app plays this in its own player; trailer_url is the plain link.
        'trailer_youtube_id': video_id,
        'backdrop_url': extras.get('backdrop_url'),
        'trailer_url': (
            f'https://www.youtube.com/watch?v={video_id}' if video_id else extras['trailer_url']
        ),
        'cast': extras['cast'],
        'crew': extras['crew'],
        # Watchmode first; the older RapidAPI lookup only when Watchmode has nothing.
        'watch_providers': (
            {'link': None, 'available': sources} if sources else watch_providers(film_id)
        ),
    }
