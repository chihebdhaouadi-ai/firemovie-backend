from django.urls import path

from . import views

# Mounted at /api/upcoming/
urlpatterns = [
    path('', views.UpcomingFilmsView.as_view(), name='upcoming_list'),
]
