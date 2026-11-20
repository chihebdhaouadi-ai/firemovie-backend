from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.models import User
from takes.services import friend_ids

from .models import Ballot, Block, Conversation, GroupVote, Membership, Message, PollVote, Reaction, Report

MAX_TITLE = 60
MAX_DESCRIPTION = 300
MAX_BODY = 2000
MESSAGES_PAGE = 100
VOTE_LENGTH = timedelta(hours=24)
MAX_REACTION = 16
MAX_POLL_OPTION = 80
# Reactions anyone may use on a post that does not limit them.
MEDIA_KINDS = {Message.Kind.PHOTO, Message.Kind.VIDEO}


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
        else:
            # Opening a chat you deleted brings it back (its history stays
            # cleared).
            Membership.objects.filter(conversation=conversation, user=user, hidden=True).update(hidden=False)
    return conversation


def _clean_title(title):
    title = (title or '').strip()
    if not title:
        raise MessagingError(400, 'title_required', 'Give it a name.')
    if len(title) > MAX_TITLE:
        raise MessagingError(400, 'title_too_long', f'Names are at most {MAX_TITLE} characters.')
    return title


def _clean_description(description):
    description = (description or '').strip()
    if len(description) > MAX_DESCRIPTION:
        raise MessagingError(
            400, 'description_too_long', f'Descriptions are at most {MAX_DESCRIPTION} characters.'
        )
    return description


def create_group(user, kind, title, member_ids, description=''):
    """A group or private topic with the creator and the chosen friends."""
    if kind not in (Conversation.Kind.GROUP, Conversation.Kind.TOPIC):
        raise MessagingError(400, 'invalid_kind', 'Unknown conversation kind.')
    title = _clean_title(title)
    description = _clean_description(description)
    ids = {int(i) for i in member_ids or []} - {user.id}
    _require_friends(user, ids)
    with transaction.atomic():
        conversation = Conversation.objects.create(
            kind=kind, title=title, description=description, created_by=user
        )
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


def update_group(user, conversation_id, title=None, description=None, photo=None):
    """Renames a group or topic, or changes its description or photo. Any
    member may do it; direct chats have none of these."""
    conversation = membership_of(user, conversation_id).conversation
    if conversation.kind == Conversation.Kind.DIRECT:
        raise MessagingError(400, 'direct_chat', 'Direct chats have no name or photo.')
    fields = []
    if title is not None:
        conversation.title = _clean_title(title)
        fields.append('title')
    if description is not None:
        conversation.description = _clean_description(description)
        fields.append('description')
    if photo is not None:
        if conversation.photo:
            conversation.photo.delete(save=False)
        conversation.photo = photo
        fields.append('photo')
    if fields:
        conversation.save(update_fields=fields)
    return conversation


def _post(conversation_id, sender, membership=None, **fields):
    """Saves a message, moves the chat to the top and, for the sender's own
    messages, marks the chat as read."""
    message = Message.objects.create(conversation_id=conversation_id, sender=sender, **fields)
    Conversation.objects.filter(pk=conversation_id).update(updated_at=message.created_at)
    # A new message brings a deleted chat back to the inbox.
    Membership.objects.filter(conversation_id=conversation_id, hidden=True).update(hidden=False)
    if membership is not None:
        membership.last_read_at = message.created_at
        membership.save(update_fields=['last_read_at'])
    return message


def _system(conversation_id, actor, event, target=None):
    payload = {'event': event}
    if target is not None:
        payload['target'] = target.username
    return _post(conversation_id, actor, kind=Message.Kind.SYSTEM, payload=payload)


def _clean_reactions(allowed):
    allowed = [str(e).strip() for e in (allowed or []) if str(e).strip()]
    if any(len(e) > MAX_REACTION for e in allowed):
        raise MessagingError(400, 'invalid_reaction', 'That is not an emoji.')
    return list(dict.fromkeys(allowed))[:10]


def _clean_payload(kind, payload):
    payload = payload or {}
    if kind == Message.Kind.GIF:
        name = str(payload.get('gif', '')).strip()[:40]
        if not name:
            raise MessagingError(400, 'invalid_gif', 'Pick a GIF.')
        return {'gif': name}
    if kind == Message.Kind.STICKER:
        sticker = str(payload.get('sticker', '')).strip()
        if not sticker or len(sticker) > MAX_REACTION:
            raise MessagingError(400, 'invalid_sticker', 'Pick a sticker.')
        return {'sticker': sticker}
    if kind == Message.Kind.MOVIE:
        movie = payload.get('movie') or {}
        title = str(movie.get('title', '')).strip()[:200]
        if not title:
            raise MessagingError(400, 'invalid_movie', 'Pick a movie.')
        return {'movie': {
            'id': movie.get('id'),
            'title': title,
            'year': str(movie.get('year') or '')[:4],
            'poster': str(movie.get('poster') or '')[:500] or None,
        }}
    if kind == Message.Kind.POLL:
        poll = payload.get('poll') or {}
        question = str(poll.get('question', '')).strip()[:200]
        options = [str(o).strip()[:MAX_POLL_OPTION] for o in poll.get('options') or []]
        options = [o for o in options if o]
        if not question or not 2 <= len(options) <= 4:
            raise MessagingError(400, 'invalid_poll', 'Add a question and two to four options.')
        return {'poll': {'question': question, 'options': options}}
    return {}


def send_message(user, conversation_id, body, kind=Message.Kind.TEXT, reply_to=None,
                 payload=None, attachment=None, allowed_reactions=None):
    """A text, GIF, sticker, photo, video, movie card or poll, optionally
    replying to another message of the same chat."""
    membership = membership_of(user, conversation_id)
    _require_not_blocked(user, membership.conversation)
    body = (body or '').strip()
    # Take and list cards are only posted by the app itself (shares and mentions).
    if kind in (Message.Kind.SYSTEM, Message.Kind.TAKE, Message.Kind.LIST) or kind not in Message.Kind.values:
        raise MessagingError(400, 'invalid_kind', 'Unknown message kind.')
    if kind == Message.Kind.TEXT and not body:
        raise MessagingError(400, 'empty_message', 'Write something first.')
    if len(body) > MAX_BODY:
        raise MessagingError(400, 'message_too_long', f'Messages are at most {MAX_BODY} characters.')
    if kind in MEDIA_KINDS and not attachment:
        raise MessagingError(400, 'file_required', 'Choose a file first.')
    if kind not in MEDIA_KINDS:
        attachment = None
    parent = None
    if reply_to is not None:
        parent = Message.objects.filter(pk=reply_to, conversation_id=conversation_id).first()
        if parent is None:
            raise MessagingError(400, 'invalid_reply', 'That message is not in this chat.')
    with transaction.atomic():
        message = _post(
            conversation_id,
            user,
            membership,
            kind=kind,
            body=body,
            reply_to=parent,
            payload=_clean_payload(kind, payload),
            attachment=attachment,
            allowed_reactions=_clean_reactions(allowed_reactions),
        )
    return message


MAX_CARD_TEXT = 200


def take_card(item, comment=None, event='shared'):
    """The payload of a take card: a snapshot of the take (a feed item) and,
    for a mention, of the comment that tagged the friend."""
    film = item.get('film') or {}
    payload = {
        'event': event,
        'take': {
            'id': item['id'],
            'tag': item.get('tag') or '',
            'title': (item.get('title') or '')[:MAX_CARD_TEXT],
            'body': (item.get('body') or '')[:MAX_CARD_TEXT],
            'author': item.get('author_name') or '',
            'author_avatar': item.get('author_avatar'),
            'film_title': film.get('title'),
            'poster': film.get('poster_url'),
        },
    }
    if comment is not None:
        payload['comment'] = {
            'id': comment.id,
            'parent_id': comment.parent_id,
            'body': comment.body[:MAX_CARD_TEXT],
        }
    return payload


def list_card(item):
    """The payload of a list card: a snapshot of the list (a list item)."""
    owner = item.get('owner') or {}
    return {
        'event': 'shared',
        'list': {
            'id': item['id'],
            'name': (item.get('name') or '')[:MAX_CARD_TEXT],
            'owner': owner.get('username') or '',
            'film_count': item.get('film_count') or 0,
            'posters': list(item.get('posters') or [])[:4],
        },
    }


def post_list_card(sender, recipient_id, payload, note=''):
    """Posts a list card in the direct chat with a friend, like a take card."""
    return post_take_card(sender, recipient_id, payload, note=note, kind=Message.Kind.LIST)


def post_take_card(sender, recipient_id, payload, note='', kind=Message.Kind.TAKE):
    """Posts a take card in the direct chat with a friend (opening the chat if
    needed). Skipped quietly when either of them blocked the other."""
    if Block.objects.filter(
        Q(blocker=sender, blocked_id=recipient_id) | Q(blocker_id=recipient_id, blocked=sender)
    ).exists():
        return None
    conversation = open_direct(sender, recipient_id)
    membership = Membership.objects.get(conversation=conversation, user=sender)
    return _post(
        conversation.id,
        sender,
        membership,
        kind=kind,
        body=(note or '').strip()[:MAX_BODY],
        payload=payload,
    )


def _message_in_my_chat(user, message_id):
    message = Message.objects.select_related('conversation').filter(pk=message_id).first()
    if message is None or not Membership.objects.filter(
        conversation_id=message.conversation_id, user=user
    ).exists():
        raise MessagingError(404, 'not_found', 'Message not found.')
    return message


def toggle_reaction(user, message_id, emoji):
    """Adds the reaction, or takes it back if it is already yours."""
    message = _message_in_my_chat(user, message_id)
    emoji = (emoji or '').strip()
    if not emoji or len(emoji) > MAX_REACTION or message.kind == Message.Kind.SYSTEM:
        raise MessagingError(400, 'invalid_reaction', 'That is not an emoji.')
    if message.allowed_reactions and emoji not in message.allowed_reactions:
        raise MessagingError(400, 'reaction_not_allowed', 'This post does not allow that reaction.')
    existing = Reaction.objects.filter(message=message, user=user, emoji=emoji)
    if existing.exists():
        existing.delete()
    else:
        Reaction.objects.create(message=message, user=user, emoji=emoji)
    return message


def vote_poll(user, message_id, option):
    """One choice per member; voting for your current choice removes it."""
    message = _message_in_my_chat(user, message_id)
    if message.kind != Message.Kind.POLL:
        raise MessagingError(400, 'not_a_poll', 'That message is not a poll.')
    options = message.payload.get('poll', {}).get('options', [])
    if not 0 <= option < len(options):
        raise MessagingError(400, 'invalid_option', 'Unknown option.')
    current = PollVote.objects.filter(message=message, user=user).first()
    if current is not None and current.option == option:
        current.delete()
    elif current is not None:
        current.option = option
        current.save(update_fields=['option'])
    else:
        PollVote.objects.create(message=message, user=user, option=option)
    return message


def _require_owner(user, conversation):
    if conversation.kind == Conversation.Kind.DIRECT:
        raise MessagingError(400, 'direct_chat', 'Direct chats have no owner.')
    if conversation.created_by_id != user.id:
        raise MessagingError(403, 'not_owner', 'Only the group creator can do that.')


def toggle_pin(user, message_id):
    message = _message_in_my_chat(user, message_id)
    _require_owner(user, message.conversation)
    if message.kind == Message.Kind.SYSTEM:
        raise MessagingError(400, 'invalid_pin', 'System lines cannot be pinned.')
    with transaction.atomic():
        message.pinned = not message.pinned
        message.save(update_fields=['pinned'])
        if message.pinned:
            _system(message.conversation_id, user, 'pinned')
    return message


def _member(conversation, user_id):
    membership = Membership.objects.select_related('user').filter(
        conversation=conversation, user_id=user_id
    ).first()
    if membership is None:
        raise MessagingError(404, 'not_member', 'That person is not in this group.')
    return membership


def remove_member(user, conversation_id, user_id):
    conversation = membership_of(user, conversation_id).conversation
    _require_owner(user, conversation)
    if user_id == user.id:
        raise MessagingError(400, 'self_remove', 'Leave the group instead.')
    target = _member(conversation, user_id)
    with transaction.atomic():
        target.delete()
        Ballot.objects.filter(vote__conversation=conversation, user_id=user_id).delete()
        Ballot.objects.filter(vote__conversation=conversation, choice=str(user_id)).delete()
        _system(conversation.id, user, 'removed', target.user)
    return conversation


def make_heritage(user, conversation_id, user_id):
    """Hands the group to another member, who becomes Heritage creator; the
    old creator stays as a regular member."""
    conversation = membership_of(user, conversation_id).conversation
    _require_owner(user, conversation)
    if user_id == user.id:
        raise MessagingError(400, 'already_owner', 'You already own this group.')
    target = _member(conversation, user_id)
    with transaction.atomic():
        _hand_over(conversation, target.user)
        GroupVote.objects.filter(conversation=conversation).delete()
        _system(conversation.id, user, 'heritage', target.user)
    return conversation


def _hand_over(conversation, new_owner):
    conversation.created_by = new_owner
    conversation.heritage = True
    conversation.save(update_fields=['created_by', 'heritage'])


def leave(user, conversation_id, pass_to=None):
    """Leaves a group. The creator must hand it over first ([pass_to]) or
    start a group vote instead; the last member out deletes the group."""
    membership = membership_of(user, conversation_id)
    conversation = membership.conversation
    if conversation.kind == Conversation.Kind.DIRECT:
        raise MessagingError(400, 'direct_chat', 'You cannot leave a direct chat.')
    if GroupVote.objects.filter(conversation=conversation).exists() and conversation.created_by_id == user.id:
        raise MessagingError(400, 'vote_running', 'A vote is already running.')
    others = Membership.objects.filter(conversation=conversation).exclude(user=user)
    with transaction.atomic():
        if not others.exists():
            conversation.delete()
            return None
        if conversation.created_by_id == user.id:
            if pass_to is None:
                raise MessagingError(400, 'owner_must_choose', 'Pass the creator tag or start a vote first.')
            new_owner = _member(conversation, pass_to).user
            if new_owner.id == user.id:
                raise MessagingError(400, 'already_owner', 'Pick someone else.')
            _hand_over(conversation, new_owner)
            membership.delete()
            _system(conversation.id, user, 'passed', new_owner)
        else:
            membership.delete()
            _system(conversation.id, user, 'left')
    return conversation


def start_vote(user, conversation_id):
    conversation = membership_of(user, conversation_id).conversation
    _require_owner(user, conversation)
    if GroupVote.objects.filter(conversation=conversation).exists():
        raise MessagingError(400, 'vote_running', 'A vote is already running.')
    with transaction.atomic():
        GroupVote.objects.create(
            conversation=conversation, started_by=user, ends_at=timezone.now() + VOTE_LENGTH
        )
        _system(conversation.id, user, 'vote_started')
    return conversation


def cancel_vote(user, conversation_id):
    conversation = membership_of(user, conversation_id).conversation
    vote = GroupVote.objects.filter(conversation=conversation, started_by=user).first()
    if vote is None:
        raise MessagingError(404, 'no_vote', 'There is no vote of yours to cancel.')
    with transaction.atomic():
        vote.delete()
        _system(conversation.id, user, 'vote_cancelled')
    return conversation


def cast_ballot(user, conversation_id, choice):
    conversation = membership_of(user, conversation_id).conversation
    settle_votes([conversation.id])
    vote = GroupVote.objects.filter(conversation_id=conversation.id).first()
    if vote is None:
        raise MessagingError(404, 'no_vote', 'There is no vote running.')
    choice = str(choice)
    if vote.stage == GroupVote.Stage.KEEP:
        if vote.started_by_id == user.id:
            raise MessagingError(400, 'own_vote', 'You cannot vote on your own poll.')
        if choice not in ('stay', 'delete'):
            raise MessagingError(400, 'invalid_choice', 'Vote Stay or Delete.')
    else:
        if choice == str(user.id) or choice == str(vote.started_by_id):
            raise MessagingError(400, 'invalid_choice', 'Pick another member.')
        if not Membership.objects.filter(conversation_id=conversation.id, user_id=choice).exists():
            raise MessagingError(400, 'invalid_choice', 'That person is not in this group.')
    Ballot.objects.update_or_create(vote=vote, user=user, defaults={'choice': choice})
    return conversation


def settle_votes(conversation_ids):
    """Closes the votes whose 24 hours are over: the first stage deletes the
    group or opens the owner vote; the second hands the group to the winner
    and the creator who asked to leave leaves."""
    now = timezone.now()
    for vote in GroupVote.objects.filter(conversation_id__in=conversation_ids, ends_at__lte=now).select_related(
        'conversation', 'started_by'
    ):
        with transaction.atomic():
            tally = Counter(vote.ballots.values_list('choice', flat=True))
            conversation = vote.conversation
            if vote.stage == GroupVote.Stage.KEEP:
                if tally['delete'] > tally['stay']:
                    conversation.delete()
                    continue
                vote.ballots.all().delete()
                vote.stage = GroupVote.Stage.OWNER
                vote.ends_at = now + VOTE_LENGTH
                vote.save(update_fields=['stage', 'ends_at'])
                _system(conversation.id, vote.started_by, 'vote_keep')
                continue
            candidates = list(
                Membership.objects.filter(conversation=conversation)
                .exclude(user=vote.started_by)
                .order_by('joined_at', 'id')
                .select_related('user')
            )
            if not candidates:
                vote.delete()
                continue
            # Most votes wins; a tie goes to whoever joined first.
            winner = max(candidates, key=lambda m: tally[str(m.user_id)]).user
            _hand_over(conversation, winner)
            vote.delete()
            Membership.objects.filter(conversation=conversation, user=vote.started_by).delete()
            _system(conversation.id, vote.started_by, 'left')
            _system(conversation.id, vote.started_by, 'vote_owner_won', winner)


def messages(user, conversation_id, after=None):
    """Messages of a conversation, oldest first (the newest page, or only
    those after message [after]). Reading them marks the chat as read."""
    settle_votes([conversation_id])
    membership = membership_of(user, conversation_id)
    queryset = (
        Message.objects.select_related('sender', 'reply_to__sender')
        .prefetch_related('reactions', 'poll_votes')
        .filter(conversation_id=conversation_id)
    )
    if membership.cleared_at is not None:
        queryset = queryset.filter(created_at__gt=membership.cleared_at)
    if after is not None:
        rows = list(queryset.filter(id__gt=after).order_by('id')[:MESSAGES_PAGE])
    else:
        rows = list(queryset.order_by('-id')[:MESSAGES_PAGE])
        rows.reverse()
    membership.last_read_at = timezone.now()
    membership.marked_unread = False
    membership.save(update_fields=['last_read_at', 'marked_unread'])
    return rows


def conversations(user):
    """The user's conversations, most recently active first, each with its
    members, last message and how many messages are unread."""
    settle_votes(Membership.objects.filter(user=user).values_list('conversation_id', flat=True))
    memberships = list(Membership.objects.filter(user=user, hidden=False).select_related('conversation'))
    convo_ids = [m.conversation_id for m in memberships]
    if not convo_ids:
        return []
    mine = {m.conversation_id: m for m in memberships}
    # Unread counts and the last message start after a cleared history.
    since = {
        m.conversation_id: max(filter(None, [m.last_read_at, m.cleared_at]), default=None)
        for m in memberships
    }

    last_ids = (
        Message.objects.filter(conversation_id=OuterRef('pk'))
        .order_by('-id')
        .values('id')[:1]
    )
    convos = list(
        Conversation.objects.filter(pk__in=convo_ids)
        .annotate(last_message_id=Subquery(last_ids))
        .prefetch_related('memberships__user', 'vote__ballots')
        .order_by('-updated_at', '-id')
    )
    last_messages = {
        m.id: m
        for m in Message.objects.select_related('sender', 'reply_to__sender')
        .prefetch_related('reactions', 'poll_votes')
        .filter(id__in=[c.last_message_id for c in convos if c.last_message_id])
    }

    unread_filter = Q()
    for convo_id, read_at in since.items():
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
    blocked_by_me = set(Block.objects.filter(blocker=user).values_list('blocked_id', flat=True))
    blocked_me = set(Block.objects.filter(blocked=user).values_list('blocker_id', flat=True))

    rows = []
    for convo in convos:
        membership = mine[convo.id]
        member_rows = list(convo.memberships.all())
        members = [m.user for m in member_rows]
        last = last_messages.get(convo.last_message_id)
        if last is not None and membership.cleared_at is not None and last.created_at <= membership.cleared_at:
            last = None
        block = None
        seen_at = None
        if convo.kind == Conversation.Kind.DIRECT:
            other = next((m for m in member_rows if m.user_id != user.id), None)
            if other is not None:
                if other.user_id in blocked_by_me:
                    block = 'me'
                elif other.user_id in blocked_me:
                    block = 'them'
                seen_at = other.last_read_at
        rows.append({
            'conversation': convo,
            'members': members,
            'last_message': last,
            'unread': unread.get(convo.id, 0),
            'muted': membership.muted,
            'pinned': membership.pinned,
            'marked_unread': membership.marked_unread,
            'block': block,
            'seen_at': seen_at,
        })
    # Pinned chats first, each group newest first.
    rows.sort(key=lambda r: not r['pinned'])
    return rows


def conversation_row(user, conversation):
    for row in conversations(user):
        if row['conversation'].id == conversation.id:
            return row
    raise MessagingError(404, 'not_found', 'Conversation not found.')


# --- Chat settings, history, blocking, editing and reports -----------------


def update_settings(user, conversation_id, muted=None, pinned=None, unread=None):
    """This member's own mute / pin / mark-as-unread settings for a chat."""
    membership = membership_of(user, conversation_id)
    fields = []
    for name, value in (('muted', muted), ('pinned', pinned), ('marked_unread', unread)):
        if value is not None:
            setattr(membership, name, bool(value))
            fields.append(name)
    if unread is False:
        membership.last_read_at = timezone.now()
        fields.append('last_read_at')
    if fields:
        membership.save(update_fields=fields)
    return membership.conversation


def clear_history(user, conversation_id):
    """Hides every message so far, for this member only."""
    membership = membership_of(user, conversation_id)
    membership.cleared_at = timezone.now()
    membership.marked_unread = False
    membership.save(update_fields=['cleared_at', 'marked_unread'])
    return membership.conversation


def delete_chat(user, conversation_id):
    """Removes a direct chat from this member's inbox and clears its history
    for them; it comes back if a new message arrives. Groups are left
    instead."""
    membership = membership_of(user, conversation_id)
    if membership.conversation.kind != Conversation.Kind.DIRECT:
        raise MessagingError(400, 'group_chat', 'Leave the group instead.')
    membership.cleared_at = timezone.now()
    membership.hidden = True
    membership.pinned = False
    membership.marked_unread = False
    membership.save(update_fields=['cleared_at', 'hidden', 'pinned', 'marked_unread'])


def _require_not_blocked(user, conversation):
    if conversation.kind != Conversation.Kind.DIRECT:
        return
    other_id = (
        Membership.objects.filter(conversation=conversation).exclude(user=user)
        .values_list('user_id', flat=True).first()
    )
    if other_id is None:
        return
    if Block.objects.filter(blocker=user, blocked_id=other_id).exists():
        raise MessagingError(403, 'you_blocked', 'Unblock them to send a message.')
    if Block.objects.filter(blocker_id=other_id, blocked=user).exists():
        raise MessagingError(403, 'blocked', "You can't reply to this conversation.")


def block(user, other_id):
    if other_id == user.id:
        raise MessagingError(400, 'self_block', 'You cannot block yourself.')
    other = User.objects.filter(pk=other_id).first()
    if other is None:
        raise MessagingError(404, 'not_found', 'User not found.')
    Block.objects.get_or_create(blocker=user, blocked=other)
    return other


def unblock(user, other_id):
    Block.objects.filter(blocker=user, blocked_id=other_id).delete()


def blocked_users(user):
    return [b.blocked for b in Block.objects.filter(blocker=user).select_related('blocked').order_by('-created_at')]


def edit_message(user, message_id, body):
    """Changes the text of your own text message."""
    message = _message_in_my_chat(user, message_id)
    if message.sender_id != user.id or message.kind != Message.Kind.TEXT or message.deleted:
        raise MessagingError(403, 'not_editable', 'You can only edit your own text messages.')
    _require_not_blocked(user, message.conversation)
    body = (body or '').strip()
    if not body:
        raise MessagingError(400, 'empty_message', 'Write something first.')
    if len(body) > MAX_BODY:
        raise MessagingError(400, 'message_too_long', f'Messages are at most {MAX_BODY} characters.')
    if body != message.body:
        message.body = body
        message.edited_at = timezone.now()
        message.save(update_fields=['body', 'edited_at'])
    return message


def delete_message(user, message_id):
    """Deletes a message for everyone: your own, or any message in a group
    you own. A placeholder stays in its place."""
    message = _message_in_my_chat(user, message_id)
    if message.kind == Message.Kind.SYSTEM:
        raise MessagingError(400, 'not_deletable', 'System lines cannot be deleted.')
    convo = message.conversation
    is_owner = convo.kind != Conversation.Kind.DIRECT and convo.created_by_id == user.id
    if message.sender_id != user.id and not is_owner:
        raise MessagingError(403, 'not_yours', 'You can only delete your own messages.')
    if message.deleted:
        return message
    with transaction.atomic():
        if message.attachment:
            message.attachment.delete(save=False)
        message.body = ''
        message.payload = {}
        message.attachment = None
        message.pinned = False
        message.deleted = True
        message.save(update_fields=['body', 'payload', 'attachment', 'pinned', 'deleted'])
        message.reactions.all().delete()
        message.poll_votes.all().delete()
    return message


def report(user, conversation_id, reason, message_id=None, details=''):
    conversation = membership_of(user, conversation_id).conversation
    if reason not in Report.Reason.values:
        raise MessagingError(400, 'invalid_reason', 'Pick a reason.')
    message = None
    if message_id is not None:
        message = Message.objects.filter(pk=message_id, conversation=conversation).first()
        if message is None:
            raise MessagingError(400, 'invalid_message', 'That message is not in this chat.')
    return Report.objects.create(
        reporter=user,
        conversation=conversation,
        message=message,
        reason=reason,
        details=(details or '').strip()[:500],
    )


def add_members(user, conversation_id, user_ids):
    """The group creator adds friends to a group or topic."""
    conversation = membership_of(user, conversation_id).conversation
    _require_owner(user, conversation)
    ids = {int(i) for i in user_ids or []} - {user.id}
    if not ids:
        raise MessagingError(400, 'no_members', 'Pick someone to add.')
    _require_friends(user, ids)
    existing = set(Membership.objects.filter(conversation=conversation).values_list('user_id', flat=True))
    new = User.objects.filter(pk__in=ids - existing).order_by('username')
    with transaction.atomic():
        for person in new:
            # Joins with the earlier messages already read.
            Membership.objects.create(conversation=conversation, user=person, last_read_at=timezone.now())
            _system(conversation.id, user, 'added', person)
    return conversation
