from django.urls import path
from . import views

urlpatterns = [
    path('get_review', views.get_reviews, name='get_reviews'),
    path('add_review', views.add_review, name='add_review'),
]