from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.models import User
from takes.services import friend_ids

from .models import Conversation, Membership, Message

MAX_TITLE = 60
MAX_BODY = 2000
MESSAGES_PAGE = 100


class MessagingError(APIException):
    def __init__(self, status_code, code, detail):
        self.status_code = status_code
        super().__init__(detail=detail, code=code)


def _direct_key(a_id, b_id):
    low, high = sorted((a_id, b_id))
    return f'{low}:{high}'


def _require_friends(user, ids):
    friends = friend_ids(user)
    strangers = set(ids) - friends - {user.id}
    if strangers:
        raise MessagingError(400, 'not_friends', 'You can only chat with your friends.')


def open_direct(user, other_id):
    """The one-to-one chat with a friend, created on first use."""
    if other_id == user.id:
        raise MessagingError(400, 'self_chat', 'You cannot message yourself.')
    other = User.objects.filter(pk=other_id).first()
    if other is None:
        raise MessagingError(404, 'not_found', 'User not found.')
    _require_friends(user, [other_id])
    key = _direct_key(user.id, other_id)
    with transaction.atomic():
        conversation, created = Conversation.objects.get_or_create(
            direct_key=key,
            defaults={'kind': Conversation.Kind.DIRECT, 'created_by': user},
        )
        if created:
            Membership.objects.bulk_create([
                Membership(conversation=conversation, user=user),
                Membership(conversation=conversation, user=other),
            ])
    return conversation


def create_group(user, kind, title, member_ids):
    """A group or private topic with the creator and the chosen friends."""
    if kind not in (Conversation.Kind.GROUP, Conversation.Kind.TOPIC):
        raise MessagingError(400, 'invalid_kind', 'Unknown conversation kind.')
    title = (title or '').strip()
    if not title:
        raise MessagingError(400, 'title_required', 'Give it a name.')
    if len(title) > MAX_TITLE:
        raise MessagingError(400, 'title_too_long', f'Names are at most {MAX_TITLE} characters.')
    ids = {int(i) for i in member_ids or []} - {user.id}
    _require_friends(user, ids)
    with transaction.atomic():
        conversation = Conversation.objects.create(kind=kind, title=title, created_by=user)
        Membership.objects.bulk_create(
            [Membership(conversation=conversation, user=user)]
            + [Membership(conversation=conversation, user_id=i) for i in ids]
        )
    return conversation


def membership_of(user, conversation_id):
    membership = (
        Membership.objects.select_related('conversation')
        .filter(conversation_id=conversation_id, user=user)
        .first()
    )
    if membership is None:
        raise MessagingError(404, 'not_found', 'Conversation not found.')
    return membership


def send_message(user, conversation_id, body):
    membership = membership_of(user, conversation_id)
    body = (body or '').strip()
    if not body:
        raise MessagingError(400, 'empty_message', 'Write something first.')
    if len(body) > MAX_BODY:
        raise MessagingError(400, 'message_too_long', f'Messages are at most {MAX_BODY} characters.')
    with transaction.atomic():
        message = Message.objects.create(
            conversation_id=conversation_id, sender=user, body=body
        )
        Conversation.objects.filter(pk=conversation_id).update(updated_at=message.created_at)
        # Your own message counts as read.
        membership.last_read_at = message.created_at
        membership.save(update_fields=['last_read_at'])
    return message


def messages(user, conversation_id, after=None):
    """Messages of a conversation, oldest first (the newest page, or only
    those after message [after]). Reading them marks the chat as read."""
    membership = membership_of(user, conversation_id)
    queryset = Message.objects.select_related('sender').filter(conversation_id=conversation_id)
    if after is not None:
        rows = list(queryset.filter(id__gt=after).order_by('id')[:MESSAGES_PAGE])
    else:
        rows = list(queryset.order_by('-id')[:MESSAGES_PAGE])
        rows.reverse()
    membership.last_read_at = timezone.now()
    membership.save(update_fields=['last_read_at'])
    return rows


def conversations(user):
    """The user's conversations, most recently active first, each with its
    members, last message and how many messages are unread."""
    memberships = Membership.objects.filter(user=user).select_related('conversation')
    convo_ids = [m.conversation_id for m in memberships]
    if not convo_ids:
        return []
    last_read = {m.conversation_id: m.last_read_at for m in memberships}

    last_ids = (
        Message.objects.filter(conversation_id=OuterRef('pk'))
        .order_by('-id')
        .values('id')[:1]
    )
    convos = list(
        Conversation.objects.filter(pk__in=convo_ids)
        .annotate(last_message_id=Subquery(last_ids))
        .prefetch_related('memberships__user')
        .order_by('-updated_at', '-id')
    )
    last_messages = {
        m.id: m
        for m in Message.objects.select_related('sender').filter(
            id__in=[c.last_message_id for c in convos if c.last_message_id]
        )
    }

    unread_filter = Q()
    for convo_id, read_at in last_read.items():
        clause = Q(conversation_id=convo_id)
        if read_at is not None:
            clause &= Q(created_at__gt=read_at)
        unread_filter |= clause
    unread = dict(
        Message.objects.filter(unread_filter)
        .exclude(sender=user)
        .values('conversation_id')
        .annotate(n=Count('id'))
        .values_list('conversation_id', 'n')
    )

    rows = []
    for convo in convos:
        members = [m.user for m in convo.memberships.all()]
        rows.append({
            'conversation': convo,
            'members': members,
            'last_message': last_messages.get(convo.last_message_id),
            'unread': unread.get(convo.id, 0),
        })
    return rows


def conversation_row(user, conversation):
    for row in conversations(user):
        if row['conversation'].id == conversation.id:
            return row
    raise MessagingError(404, 'not_found', 'Conversation not found.')
