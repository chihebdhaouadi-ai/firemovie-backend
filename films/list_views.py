from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    AddFilmSerializer,
    AddTop5Serializer,
    EntrySerializer,
    MoveTop5Serializer,
)
from .services import (
    TOP_5,
    WATCHED,
    WATCHLIST,
    add_top5,
    add_watched,
    add_watchlist,
    counts_for,
    entries_for,
    move_top5,
    remove_entry,
)


class ListPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ListCountsView(APIView):
    def get(self, request):
        return Response(counts_for(request.user))


class _EntryCollectionView(APIView):
    list_type = None

    def get(self, request):
        paginator = ListPagination()
        page = paginator.paginate_queryset(
            entries_for(request.user, self.list_type), request, view=self,
        )
        return paginator.get_paginated_response(EntrySerializer(page, many=True).data)


class _EntryItemView(APIView):
    list_type = None

    def delete(self, request, film_id):
        remove_entry(request.user, self.list_type, film_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class Top5CollectionView(_EntryCollectionView):
    list_type = TOP_5

    def post(self, request):
        serializer = AddTop5Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        entry, created = add_top5(
            request.user,
            data['film_id'],
            slot=data.get('slot'),
            replace=data['replace'],
        )
        return Response(
            EntrySerializer(entry).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class Top5ItemView(_EntryItemView):
    list_type = TOP_5

    def patch(self, request, film_id):
        serializer = MoveTop5Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry = move_top5(request.user, film_id, serializer.validated_data['slot'])
        return Response(EntrySerializer(entry).data)


class WatchedCollectionView(_EntryCollectionView):
    list_type = WATCHED

    def post(self, request):
        serializer = AddFilmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry, created, removed_from_watchlist = add_watched(
            request.user, serializer.validated_data['film_id'],
        )
        body = dict(EntrySerializer(entry).data)
        body['removed_from_watchlist'] = removed_from_watchlist
        return Response(
            body,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WatchedItemView(_EntryItemView):
    list_type = WATCHED


class WatchlistCollectionView(_EntryCollectionView):
    list_type = WATCHLIST

    def post(self, request):
        serializer = AddFilmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entry, created = add_watchlist(request.user, serializer.validated_data['film_id'])
        return Response(
            EntrySerializer(entry).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class WatchlistItemView(_EntryItemView):
    list_type = WATCHLIST
