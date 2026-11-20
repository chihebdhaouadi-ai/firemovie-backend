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
    path('conversations/<int:conversation_id>/settings/', views.chat_settings, name='messaging_settings'),
    path('conversations/<int:conversation_id>/clear/', views.clear_history, name='messaging_clear'),
    path('conversations/<int:conversation_id>/delete/', views.delete_chat, name='messaging_delete'),
    path('conversations/<int:conversation_id>/members/', views.add_members, name='messaging_add_members'),
    path('conversations/<int:conversation_id>/report/', views.report, name='messaging_report'),
    path('messages/<int:message_id>/', views.message_detail, name='messaging_message'),
    path('blocks/', views.blocks, name='messaging_blocks'),
    path('blocks/<int:user_id>/', views.block, name='messaging_block'),
    path('messages/<int:message_id>/react/', views.react, name='messaging_react'),
    path('messages/<int:message_id>/pin/', views.pin, name='messaging_pin'),
    path('messages/<int:message_id>/vote/', views.poll_vote, name='messaging_poll_vote'),
]
