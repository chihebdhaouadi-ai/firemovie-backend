from django.urls import path

from . import views

# Mounted at /api/articles/
urlpatterns = [
    path('', views.LatestArticlesView.as_view(), name='articles_latest'),
]
