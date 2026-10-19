from django.urls import path

from . import views

urlpatterns = [
    path('users/search', views.user_search, name='social_user_search'),
    path('me/connections', views.connections, name='social_connections'),
    path('friend-requests', views.create_friend_request, name='social_friend_request_create'),
    path('friend-requests/<int:request_id>/accept', views.accept_request, name='social_friend_request_accept'),
    path('friend-requests/<int:request_id>/decline', views.decline_request, name='social_friend_request_decline'),
    path('friend-requests/<int:request_id>/cancel', views.cancel_request, name='social_friend_request_cancel'),
    path('movie-suggestions', views.create_movie_suggestions, name='social_movie_suggestions'),
    path('notifications', views.notifications, name='social_notifications'),
    path('notifications/read', views.mark_notifications_read, name='social_notifications_read'),
]
