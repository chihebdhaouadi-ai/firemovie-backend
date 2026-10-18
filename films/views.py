from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

LIST_MAP = {
    'top_5': 'top_movies',
    'watched': 'watched_movies',
    'watchlist': 'watchlist_movies',
}

UNSLUG = {
    'top_5_movies': 'top_movies',
    'wathced_list_movies': 'watched_movies',
    'watch_list_movies': 'watchlist_movies',
    'popular_friends_list_movies': 'watched_movies',  # returns popular from watched
}


def _get_list_field(user, list_slug):
    """Return the JSON field name for a given list slug."""
    return UNSLUG.get(list_slug, list_slug)


def _add_to_list(user, list_slug, imdb_id):
    field = _get_list_field(user, list_slug)
    current = getattr(user, field, [])
    if imdb_id not in current:
        current.append(imdb_id)
        setattr(user, field, current)
        user.save(update_fields=[field])
    return current


def _remove_from_list(user, list_slug, imdb_id):
    field = _get_list_field(user, list_slug)
    current = getattr(user, field, [])
    if imdb_id in current:
        current.remove(imdb_id)
        setattr(user, field, current)
        user.save(update_fields=[field])
    return current


def _get_list(user, list_slug):
    field = _get_list_field(user, list_slug)
    return getattr(user, field, [])


# ─── GET endpoints ───────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_top_5_movies(request):
    items = _get_list(request.user, 'top_movies')
    return Response({
        'data': [{'imdp_id': i} for i in items],
        'status': 200,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_watched_movies(request):
    items = _get_list(request.user, 'watched_movies')
    return Response({
        'data': [{'imdp_id': i} for i in items],
        'status': 200,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_watchlist_movies(request):
    items = _get_list(request.user, 'watchlist_movies')
    return Response({
        'data': [{'imdp_id': i} for i in items],
        'status': 200,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_popular_movies(request):
    """Return most-watched movies across all users."""
    from accounts.models import User
    from collections import Counter
    all_items = []
    for u in User.objects.all():
        all_items.extend(u.watched_movies)
    counter = Counter(all_items)
    popular = [{'imdp_id': i, 'count': c} for i, c in counter.most_common(20)]
    return Response({
        'data': popular,
        'status': 200,
    })


# ─── ADD endpoints ────────────────────────────────────────────

def _add_generic(request, list_slug):
    imdb_id = request.data.get('imdbid')
    if not imdb_id:
        return Response({'status': 400, 'message': 'imdbid required'},
                        status=status.HTTP_400_BAD_REQUEST)
    _add_to_list(request.user, list_slug, imdb_id)
    return Response({'status': 200, 'message': 'MOVIE ADD IT'},
                    status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_top_5(request):
    return _add_generic(request, 'top_movies')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_watched(request):
    return _add_generic(request, 'watched_movies')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_watchlist(request):
    return _add_generic(request, 'watchlist_movies')


# ─── DELETE endpoints ─────────────────────────────────────────

def _delete_generic(request, list_slug):
    imdb_id = request.data.get('imdbid')
    if not imdb_id:
        return Response({'status': 400, 'message': 'imdbid required'},
                        status=status.HTTP_400_BAD_REQUEST)
    _remove_from_list(request.user, list_slug, imdb_id)
    return Response({'status': 200, 'message': 'MOVIE REMOVED'},
                    status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_top_5(request):
    return _delete_generic(request, 'top_movies')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_watched(request):
    return _delete_generic(request, 'watched_movies')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_watchlist(request):
    return _delete_generic(request, 'watchlist_movies')