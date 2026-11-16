from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Max
from django.utils import timezone
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .catalog import film_detail, try_stored_film
from .models import Film, FilmEntry
from .serializers import PageParamSerializer
from .services import lists_containing
from .movie_source import film_stills, search_movies

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


class FilmDetailView(APIView):
    def get(self, request, film_id):
        payload = film_detail(film_id)
        memberships = lists_containing(request.user, [film_id])
        return Response({**payload, 'in_lists': memberships.get(film_id, [])})


class FilmStillsView(APIView):
    def get(self, request, film_id):
        return Response(film_stills(film_id))


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
