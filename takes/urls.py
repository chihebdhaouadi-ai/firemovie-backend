from django.urls import path

from . import views

urlpatterns = [
    path('films/<str:film_id>/summary/', views.film_summary, name='takes_film_summary'),
    path('films/<str:film_id>/reaction/', views.set_reaction, name='takes_film_reaction'),
    path('films/<str:film_id>/takes/', views.film_takes, name='takes_film_takes'),
    path('takes/<int:take_id>/votes/<str:kind>/', views.set_vote, name='takes_vote'),
    path('takes/<int:take_id>/comments/', views.take_comments, name='takes_comments'),
]
