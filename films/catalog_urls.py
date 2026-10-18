from django.urls import path, re_path

from . import catalog_views

urlpatterns = [
    path('search', catalog_views.FilmSearchView.as_view(), name='film_search'),
    re_path(
        r'^(?P<film_id>tt\d{1,10})/$',
        catalog_views.FilmDetailView.as_view(),
        name='film_detail',
    ),
]
