from django.urls import path, re_path

from . import list_views

FILM_ID = r'(?P<film_id>tt\d{1,10}|\d{1,12})'

urlpatterns = [
    path('', list_views.ListCountsView.as_view(), name='list_counts'),
    path('top5/', list_views.Top5CollectionView.as_view(), name='top5_collection'),
    re_path(rf'^top5/{FILM_ID}/$', list_views.Top5ItemView.as_view(), name='top5_item'),
    path('watched/', list_views.WatchedCollectionView.as_view(), name='watched_collection'),
    re_path(rf'^watched/{FILM_ID}/$', list_views.WatchedItemView.as_view(), name='watched_item'),
    path('watchlist/', list_views.WatchlistCollectionView.as_view(), name='watchlist_collection'),
    re_path(rf'^watchlist/{FILM_ID}/$', list_views.WatchlistItemView.as_view(), name='watchlist_item'),
]
