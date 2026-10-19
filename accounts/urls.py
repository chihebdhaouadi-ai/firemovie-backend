from django.urls import path
from . import views

urlpatterns = [
    path('login', views.login_view, name='login'),
    path('register', views.register_view, name='register'),
    path('profile', views.profile_view, name='profile'),
    path('users/<int:user_id>', views.public_profile_view, name='public_profile'),
]