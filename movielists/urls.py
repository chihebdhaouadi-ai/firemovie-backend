from django.urls import path

from . import views

urlpatterns = [
    path('', views.lists, name='movie_lists'),
    path('friends/', views.friends_lists, name='movie_lists_friends'),
    path('saved/', views.saved_lists, name='movie_lists_saved'),
    path('<int:list_id>/', views.list_detail, name='movie_list_detail'),
    path('<int:list_id>/like/', views.like, name='movie_list_like'),
    path('<int:list_id>/share/', views.share, name='movie_list_share'),
    path('<int:list_id>/save/', views.save, name='movie_list_save'),
    path('<int:list_id>/comments/', views.comments, name='movie_list_comments'),
]
