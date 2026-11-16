from django.urls import path

from . import views

app_name = 'articles'

# Mounted at /articles/
urlpatterns = [
    path('<slug:slug>/', views.article_detail, name='detail'),
    path('<slug:slug>/body/', views.article_body, name='body'),
]
