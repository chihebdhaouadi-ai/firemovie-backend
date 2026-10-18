from django.urls import path
from . import views

urlpatterns = [
    # GET
    path('get_top_5_movies', views.get_top_5_movies, name='get_top_5'),
    path('get_wathced_list_movies', views.get_watched_movies, name='get_watched'),
    path('get_watch_list_movies', views.get_watchlist_movies, name='get_watchlist'),
    path('get_popular_friends_list_movies', views.get_popular_movies, name='get_popular'),
    # ADD
    path('add_top_5_movies', views.add_top_5, name='add_top_5'),
    path('add_watched_movies', views.add_watched, name='add_watched'),
    path('add_watchlist_movies', views.add_watchlist, name='add_watchlist'),
    # DELETE
    path('delete_top_5_movies', views.delete_top_5, name='delete_top_5'),
    path('delete_wathced_list_movies', views.delete_watched, name='delete_watched'),
    path('delete_watch_list_movies', views.delete_watchlist, name='delete_watchlist'),
]