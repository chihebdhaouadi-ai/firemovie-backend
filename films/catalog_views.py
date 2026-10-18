from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import PageParamSerializer
from .services import lists_containing
from .movie_source import movie_detail, search_movies

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
        payload = movie_detail(film_id)
        memberships = lists_containing(request.user, [film_id])
        return Response({**payload, 'in_lists': memberships.get(film_id, [])})
