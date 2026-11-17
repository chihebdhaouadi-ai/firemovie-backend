from django.urls import path

from . import views

urlpatterns = [
    path('conversations/', views.conversations, name='messaging_conversations'),
    path(
        'conversations/<int:conversation_id>/messages/',
        views.conversation_messages,
        name='messaging_messages',
    ),
]
