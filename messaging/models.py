from django.conf import settings
from django.db import models


class Conversation(models.Model):
    """A chat: one-to-one with a friend, a group, or a private topic (a group
    around a subject that only its members can see)."""

    class Kind(models.TextChoices):
        DIRECT = 'direct', 'Direct'
        GROUP = 'group', 'Group'
        TOPIC = 'topic', 'Private topic'

    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=60, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_conversations',
    )
    # A stable key for direct chats ("<low id>:<high id>"), so two friends
    # always land in the same conversation.
    direct_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'conversations'
        ordering = ['-updated_at', '-id']


class Membership(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversation_memberships',
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'conversation_members'
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'user'], name='unique_conversation_member'),
        ]


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at', 'id']
