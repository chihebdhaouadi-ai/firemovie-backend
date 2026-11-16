from .models import Film
from .movie_source import (
    IMDB_ID_PATTERN,
    FilmNotFound,
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    fetch_film_detail,
    watch_providers,
)

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


def film_detail(film_id):
    film = stored_film(film_id)
    return {
        'film_id': film.imdb_id,
        **{field: getattr(film, field) for field in STORED_FIELDS},
        'watch_providers': watch_providers(film_id),
    }
