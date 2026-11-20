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
    # Groups and topics only: what the chat is about, and its picture.
    description = models.TextField(max_length=300, blank=True, default='')
    photo = models.FileField(upload_to='conversation_photos/', blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_conversations',
    )
    # A stable key for direct chats ("<low id>:<high id>"), so two friends
    # always land in the same conversation.
    direct_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    # True once the creator handed the group over: [created_by] is then the
    # "Heritage creator", with the same powers the original creator had.
    heritage = models.BooleanField(default=False)
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
    # This member's own settings for the chat.
    muted = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    marked_unread = models.BooleanField(default=False)
    # Messages up to this moment are hidden for this member ("Clear history").
    cleared_at = models.DateTimeField(null=True, blank=True)
    # "Delete chat" on a direct chat: gone from the inbox until a new message.
    hidden = models.BooleanField(default=False)

    class Meta:
        db_table = 'conversation_members'
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'user'], name='unique_conversation_member'),
        ]


class Message(models.Model):
    class Kind(models.TextChoices):
        TEXT = 'text', 'Text'
        SYSTEM = 'system', 'System line'
        GIF = 'gif', 'GIF'
        STICKER = 'sticker', 'Sticker'
        PHOTO = 'photo', 'Photo'
        VIDEO = 'video', 'Video'
        MOVIE = 'movie', 'Movie card'
        POLL = 'poll', 'Poll'
        # A take or topic sent to a friend, or a comment that tagged them.
        TAKE = 'take', 'Take card'
        # A movie list sent to a friend.
        LIST = 'list', 'List card'

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    # For system lines, the member who caused them.
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    # The text, or a media post's caption (may be empty then).
    body = models.TextField(max_length=2000, blank=True, default='')
    reply_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies'
    )
    attachment = models.FileField(upload_to='message_media/', blank=True, null=True)
    # Per kind: {"gif": name}, {"sticker": emoji}, {"movie": {...}},
    # {"poll": {"question", "options"}}, {"take": {...}, "comment": {...},
    # "event": "shared" | "mention"} or, for system lines,
    # {"event": ..., "target": username}.
    payload = models.JSONField(default=dict, blank=True)
    # Posts may limit reactions to these emojis; empty means any.
    allowed_reactions = models.JSONField(default=list, blank=True)
    pinned = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)
    # Deleted for everyone: the content is gone, a placeholder stays.
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'messages'
        ordering = ['created_at', 'id']


class Reaction(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=16)

    class Meta:
        db_table = 'message_reactions'
        constraints = [
            models.UniqueConstraint(fields=['message', 'user', 'emoji'], name='unique_message_reaction'),
        ]


class PollVote(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='poll_votes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    option = models.PositiveSmallIntegerField()

    class Meta:
        db_table = 'message_poll_votes'
        constraints = [
            models.UniqueConstraint(fields=['message', 'user'], name='unique_poll_vote'),
        ]


class GroupVote(models.Model):
    """The creator asked to leave and let the members decide: first whether
    to keep the group (24 hours), then who owns it (another 24 hours)."""

    class Stage(models.TextChoices):
        KEEP = 'keep', 'Keep or delete'
        OWNER = 'owner', 'New owner'

    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name='vote')
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stage = models.CharField(max_length=8, choices=Stage.choices, default=Stage.KEEP)
    ends_at = models.DateTimeField()

    class Meta:
        db_table = 'conversation_votes'


class Ballot(models.Model):
    vote = models.ForeignKey(GroupVote, on_delete=models.CASCADE, related_name='ballots')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    # "stay" / "delete" in the first stage, a member id in the second.
    choice = models.CharField(max_length=16)

    class Meta:
        db_table = 'conversation_vote_ballots'
        constraints = [
            models.UniqueConstraint(fields=['vote', 'user'], name='unique_vote_ballot'),
        ]


class Block(models.Model):
    """[blocker] blocked [blocked]: neither can message the other in their
    direct chat until it is lifted."""

    blocker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_made')
    blocked = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='blocks_received')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_blocks'
        constraints = [
            models.UniqueConstraint(fields=['blocker', 'blocked'], name='unique_user_block'),
        ]


class Report(models.Model):
    """A member reported a chat or one of its messages, for moderators."""

    class Reason(models.TextChoices):
        SPAM = 'spam', 'Spam'
        HARASSMENT = 'harassment', 'Harassment'
        HATE = 'hate', 'Hate speech'
        NSFW = 'nsfw', 'Sexual content'
        OTHER = 'other', 'Something else'

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_reports')
    conversation = models.ForeignKey(Conversation, on_delete=models.SET_NULL, null=True, related_name='reports')
    message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name='reports')
    reason = models.CharField(max_length=12, choices=Reason.choices)
    details = models.TextField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_reports'
        ordering = ['-created_at']
