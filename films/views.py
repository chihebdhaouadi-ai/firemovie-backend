from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .errors import ListRuleError
from .movie_source import (
    FilmNotFound,
    MovieSourceNotConfigured,
    MovieSourceUnavailable,
    movie_detail,
)
from .serializers import AddFilmSerializer
from .services import (
    TOP_5,
    WATCHED,
    WATCHLIST,
    add_top5,
    add_watched,
    add_watchlist,
    film_ids_for,
    popular_watched,
    remove_entry,
)


def _legacy_film_id(request):
    raw = request.data.get('imdbid')
    if not raw:
        return None, Response(
            {'status': 400, 'message': 'imdbid required'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = AddFilmSerializer(data={'film_id': raw})
    if not serializer.is_valid():
        return None, Response(
            {'status': 400, 'message': 'imdbid invalid'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return serializer.validated_data['film_id'], None


def _legacy_list_item(film_id):
    item = {'imdp_id': film_id, 'title': None, 'poster_url': None}
    try:
        detail = movie_detail(film_id)
    except (FilmNotFound, MovieSourceNotConfigured, MovieSourceUnavailable):
        return item
    item['title'] = detail['title'] or None
    item['poster_url'] = detail['poster_url']
    return item


def _legacy_list(user, list_type):
    return Response({
        'data': [_legacy_list_item(film_id) for film_id in film_ids_for(user, list_type)],
        'status': 200,
    })


def _legacy_add(request, add):
    film_id, error = _legacy_film_id(request)
    if error is not None:
        return error
    try:
        add(request.user, film_id)
    except ListRuleError as exc:
        return Response(
            {'status': exc.status_code, 'message': exc.detail},
            status=exc.status_code,
        )
    return Response({'status': 200, 'message': 'MOVIE ADD IT'})


def _legacy_delete(request, list_type):
    film_id, error = _legacy_film_id(request)
    if error is not None:
        return error
    try:
        remove_entry(request.user, list_type, film_id)
    except ListRuleError:
        pass
    return Response({'status': 200, 'message': 'MOVIE REMOVED'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_top_5_movies(request):
    return _legacy_list(request.user, TOP_5)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_watched_movies(request):
    return _legacy_list(request.user, WATCHED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_watchlist_movies(request):
    return _legacy_list(request.user, WATCHLIST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_popular_movies(request):
    popular = [
        {'imdp_id': row['film_id'], 'count': row['count']}
        for row in popular_watched(20)
    ]
    return Response({'data': popular, 'status': 200})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_top_5(request):
    return _legacy_add(request, add_top5)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_watched_movies(request):
    return _legacy_add(request, add_watched)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_watchlist_movies(request):
    return _legacy_add(request, add_watchlist)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_top_5(request):
    return _legacy_delete(request, TOP_5)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_watched(request):
    return _legacy_delete(request, WATCHED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_watchlist(request):
    return _legacy_delete(request, WATCHLIST)
