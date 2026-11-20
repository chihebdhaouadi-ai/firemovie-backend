import re
from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import film_backdrop_stills, film_detail, try_stored_film
from .models import Film, FilmEntry
from .serializers import PageParamSerializer
from .services import lists_containing
from .movie_source import (
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    film_stills,
    search_movies,
)
from .people import PersonNotFound, person_detail
from .watchmode import (
    discover_movies,
    film_genres,
    person_imdb_id,
    streaming_countries,
    streaming_providers,
)

POPULAR_WINDOW = timedelta(days=7)
POPULAR_LIMIT = 10
POPULAR_CACHE_KEY = 'films:popular_this_week'
POPULAR_CACHE_SECONDS = 60 * 10

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 100


class QueryTooShort(APIException):
    status_code = 400
    default_code = 'query_too_short'
    default_detail = f'Search needs at least {MIN_QUERY_LENGTH} characters.'


class FilmSearchView(APIView):
    def get(self, request):
        query = (request.query_params.get('q') or '').strip()[:MAX_QUERY_LENGTH]
        if len(query) < MIN_QUERY_LENGTH:
            raise QueryTooShort()
        page_params = PageParamSerializer(data={'page': request.query_params.get('page', 1)})
        page_params.is_valid(raise_exception=True)
        page = page_params.validated_data['page']

        payload = search_movies(query, page)
        ids = [row['film_id'] for row in payload['results']]
        memberships = lists_containing(request.user, ids)
        results = [
            {**row, 'in_lists': memberships.get(row['film_id'], [])}
            for row in payload['results']
        ]
        return Response({**payload, 'results': results})


class InvalidBrowseFilter(APIException):
    status_code = 400
    default_code = 'invalid_browse_filter'
    default_detail = (
        'Year must be between 1900 and next year; provider and genre must be numbers; '
        'language and country must be two-letter codes.'
    )


def _int_param(request, name):
    raw = request.query_params.get(name)
    if raw in (None, ''):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise InvalidBrowseFilter()


TWO_LETTERS = re.compile(r'[A-Za-z]{2}')


def _code_param(request, name, normalize):
    raw = request.query_params.get(name)
    if raw in (None, ''):
        return None
    if not TWO_LETTERS.fullmatch(raw):
        raise InvalidBrowseFilter()
    return normalize(raw)


class BrowseFilmsView(APIView):
    """Most popular films, optionally for one release year or one streaming service."""

    def get(self, request):
        page_params = PageParamSerializer(data={'page': request.query_params.get('page', 1)})
        page_params.is_valid(raise_exception=True)
        page = page_params.validated_data['page']
        year = _int_param(request, 'year')
        provider = _int_param(request, 'provider')
        if year is not None and not 1900 <= year <= timezone.localdate().year + 1:
            raise InvalidBrowseFilter()
        genre = _int_param(request, 'genre')
        language = _code_param(request, 'language', str.lower)
        country = _code_param(request, 'country', str.upper)
        if any(value is not None and value <= 0 for value in (provider, genre)):
            raise InvalidBrowseFilter()

        payload = discover_movies(
            page, year=year, provider_id=provider, genre_id=genre,
            language=language, country=country,
        )
        ids = [row['film_id'] for row in payload['results']]
        memberships = lists_containing(request.user, ids)
        results = [
            {**row, 'in_lists': memberships.get(row['film_id'], [])}
            for row in payload['results']
        ]
        return Response({**payload, 'results': results})


class StreamingProvidersView(APIView):
    def get(self, request):
        return Response(streaming_providers())


class FilmGenresView(APIView):
    def get(self, request):
        return Response(film_genres())


class StreamingCountriesView(APIView):
    def get(self, request):
        return Response(streaming_countries())


class FilmDetailView(APIView):
    def get(self, request, film_id):
        payload = film_detail(film_id)
        memberships = lists_containing(request.user, [film_id])
        return Response({**payload, 'in_lists': memberships.get(film_id, [])})


class FilmStillsView(APIView):
    def get(self, request, film_id):
        try:
            payload = film_stills(film_id)
        except (MovieSourceNotConfigured, MovieSourceUnavailable):
            payload = {'film_id': film_id, 'stills': []}
        if not payload['stills']:
            # The RapidAPI images source is optional; Watchmode's backdrop stands in.
            payload = film_backdrop_stills(film_id)
        return Response(payload)


class PersonDetailView(APIView):
    def get(self, request, person_id):
        return Response(person_detail(person_id))


class WatchmodePersonDetailView(APIView):
    def get(self, request, watchmode_id):
        imdb_id = person_imdb_id(int(watchmode_id))
        if imdb_id is None:
            raise PersonNotFound()
        return Response(person_detail(imdb_id))


class PopularThisWeekView(APIView):
    """Films most often added to someone's watched or watchlist this week.

    Counts adds across all users (no names are returned) and returns the top
    films with their stored details.
    """

    def get(self, request):
        cached = cache.get(POPULAR_CACHE_KEY)
        if cached is not None:
            return Response(cached)

        since = timezone.now() - POPULAR_WINDOW
        rows = list(
            FilmEntry.objects.filter(
                list_type__in=[FilmEntry.ListType.WATCHED, FilmEntry.ListType.WATCHLIST],
                created_at__gte=since,
            )
            .values('film_id')
            .annotate(adds=Count('id'), latest=Max('created_at'))
            .order_by('-adds', '-latest')[:POPULAR_LIMIT]
        )
        stored = {
            film.imdb_id: film
            for film in Film.objects.filter(imdb_id__in=[row['film_id'] for row in rows])
        }

        results = []
        for row in rows:
            # Films are stored the first time someone opens them, so a popular
            # film may still need its details fetched here (once).
            film = stored.get(row['film_id']) or try_stored_film(row['film_id'])
            if film is None:
                continue
            results.append({
                'film_id': film.imdb_id,
                'title': film.title,
                'year': film.year,
                'poster_url': film.poster_url,
                'adds': row['adds'],
            })

        cache.set(POPULAR_CACHE_KEY, results, POPULAR_CACHE_SECONDS)
        return Response(results)
