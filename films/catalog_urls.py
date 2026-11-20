from django.urls import path, re_path

from . import catalog_views

urlpatterns = [
    path('search', catalog_views.FilmSearchView.as_view(), name='film_search'),
    path('browse/', catalog_views.BrowseFilmsView.as_view(), name='film_browse'),
    path('providers/', catalog_views.StreamingProvidersView.as_view(), name='film_providers'),
    path('genres/', catalog_views.FilmGenresView.as_view(), name='film_genres'),
    path('countries/', catalog_views.StreamingCountriesView.as_view(), name='film_countries'),
    path('popular/', catalog_views.PopularThisWeekView.as_view(), name='film_popular_this_week'),
    re_path(
        r'^(?P<film_id>tt\d{1,10})/$',
        catalog_views.FilmDetailView.as_view(),
        name='film_detail',
    ),
    re_path(
        r'^(?P<film_id>tt\d{1,10})/stills/$',
        catalog_views.FilmStillsView.as_view(),
        name='film_stills',
    ),
    re_path(
        r'^people/(?P<person_id>nm\d{1,10})/$',
        catalog_views.PersonDetailView.as_view(),
        name='person_detail',
    ),
    re_path(
        r'^people/(?P<watchmode_id>\d{1,10})/$',
        catalog_views.WatchmodePersonDetailView.as_view(),
        name='watchmode_person_detail',
    ),
]
