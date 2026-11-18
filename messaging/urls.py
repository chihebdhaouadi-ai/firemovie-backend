from django.urls import path

from . import views

urlpatterns = [
    path('conversations/', views.conversations, name='messaging_conversations'),
    path(
        'conversations/<int:conversation_id>/',
        views.conversation_detail,
        name='messaging_conversation',
    ),
    path(
        'conversations/<int:conversation_id>/messages/',
        views.conversation_messages,
        name='messaging_messages',
    ),
    path(
        'conversations/<int:conversation_id>/members/<int:user_id>/remove/',
        views.remove_member,
        name='messaging_remove_member',
    ),
    path('conversations/<int:conversation_id>/owner/', views.make_heritage, name='messaging_owner'),
    path('conversations/<int:conversation_id>/leave/', views.leave, name='messaging_leave'),
    path('conversations/<int:conversation_id>/vote/', views.group_vote, name='messaging_vote'),
    path('conversations/<int:conversation_id>/vote/ballot/', views.ballot, name='messaging_ballot'),
    path('messages/<int:message_id>/react/', views.react, name='messaging_react'),
    path('messages/<int:message_id>/pin/', views.pin, name='messaging_pin'),
    path('messages/<int:message_id>/vote/', views.poll_vote, name='messaging_poll_vote'),
]
