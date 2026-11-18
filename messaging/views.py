import json

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.serializers import _validate_image
from social.serializers import UserCardSerializer

from . import services
from .models import Conversation, Message

_when = serializers.DateTimeField()


def _user(user, request):
    return UserCardSerializer(user, context={'request': request}).data


MAX_VIDEO_BYTES = 12 * 1024 * 1024
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.m4v', '.webm')


def _snippet(message):
    if message.body:
        return message.body[:80]
    if message.kind == Message.Kind.POLL:
        return message.payload.get('poll', {}).get('question', '')[:80]
    if message.kind == Message.Kind.MOVIE:
        return message.payload.get('movie', {}).get('title', '')[:80]
    return ''


def _message(message, request):
    me = request.user.id
    counts = {}
    mine = set()
    for reaction in message.reactions.all():
        counts[reaction.emoji] = counts.get(reaction.emoji, 0) + 1
        if reaction.user_id == me:
            mine.add(reaction.emoji)
    payload = dict(message.payload or {})
    if message.kind == Message.Kind.POLL:
        options = payload.get('poll', {}).get('options', [])
        tally = [0] * len(options)
        my_vote = None
        for vote in message.poll_votes.all():
            if 0 <= vote.option < len(tally):
                tally[vote.option] += 1
            if vote.user_id == me:
                my_vote = vote.option
        payload['poll'] = {**payload.get('poll', {}), 'votes': tally, 'my_vote': my_vote}
    parent = message.reply_to
    return {
        'id': message.id,
        'kind': message.kind,
        'body': message.body,
        'sender': _user(message.sender, request),
        'created_at': _when.to_representation(message.created_at),
        'reply_to': None if parent is None else {
            'id': parent.id,
            'kind': parent.kind,
            'sender': parent.sender.username,
            'snippet': _snippet(parent),
        },
        'attachment': request.build_absolute_uri(message.attachment.url) if message.attachment else None,
        'payload': payload,
        'allowed_reactions': message.allowed_reactions,
        'pinned': message.pinned,
        'reactions': [{'emoji': e, 'count': n, 'me': e in mine} for e, n in counts.items()],
    }


def _vote(convo, request):
    try:
        vote = convo.vote
    except ObjectDoesNotExist:
        return None
    ballots = list(vote.ballots.all())
    tally = {}
    for ballot in ballots:
        tally[ballot.choice] = tally.get(ballot.choice, 0) + 1
    mine = next((b.choice for b in ballots if b.user_id == request.user.id), None)
    return {
        'stage': vote.stage,
        'started_by': vote.started_by_id,
        'ends_at': _when.to_representation(vote.ends_at),
        'tally': tally,
        'my_choice': mine,
    }


def _conversation(row, request):
    convo = row['conversation']
    me = request.user
    members = row['members']
    others = [m for m in members if m.id != me.id]
    title = convo.title
    if convo.kind == Conversation.Kind.DIRECT:
        title = others[0].username if others else me.username
    last = row['last_message']
    return {
        'id': convo.id,
        'kind': convo.kind,
        'title': title,
        'description': convo.description,
        'photo': request.build_absolute_uri(convo.photo.url) if convo.photo else None,
        'created_by': convo.created_by_id,
        'heritage': convo.heritage,
        'vote': _vote(convo, request),
        'members': [_user(m, request) for m in members],
        'last_message': None if last is None else _message(last, request),
        'unread': row['unread'],
        'updated_at': _when.to_representation(convo.updated_at),
    }


class CreateConversationSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Conversation.Kind.choices)
    user_id = serializers.IntegerField(required=False)
    title = serializers.CharField(required=False, allow_blank=True)
    member_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class UpdateConversationSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    photo = serializers.FileField(required=False)

    def validate_photo(self, value):
        return _validate_image(value)


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, trim_whitespace=False, required=False, default='')
    kind = serializers.ChoiceField(choices=Message.Kind.choices, required=False, default='text')
    reply_to = serializers.IntegerField(required=False, allow_null=True)
    # JSON object / list; multipart requests send them as strings.
    payload = serializers.JSONField(required=False)
    allowed_reactions = serializers.JSONField(required=False)
    attachment = serializers.FileField(required=False)

    def validate(self, data):
        for key in ('payload', 'allowed_reactions'):
            value = data.get(key)
            if isinstance(value, str):
                try:
                    data[key] = json.loads(value) if value else None
                except ValueError:
                    raise serializers.ValidationError({key: 'Invalid JSON.'})
        if data.get('payload') is not None and not isinstance(data['payload'], dict):
            raise serializers.ValidationError({'payload': 'Expected an object.'})
        if data.get('allowed_reactions') is not None and not isinstance(data['allowed_reactions'], list):
            raise serializers.ValidationError({'allowed_reactions': 'Expected a list.'})
        file = data.get('attachment')
        if file is not None:
            if data.get('kind') == 'photo':
                data['attachment'] = _validate_image(file)
            elif data.get('kind') == 'video':
                if not file.name.lower().endswith(VIDEO_EXTENSIONS):
                    raise serializers.ValidationError({'attachment': 'Upload an MP4, MOV or WebM video.'})
                if file.size > MAX_VIDEO_BYTES:
                    raise serializers.ValidationError({'attachment': 'Videos must be 12 MB or smaller.'})
        return data


@api_view(['GET', 'POST'])
def conversations(request):
    if request.method == 'GET':
        return Response([_conversation(row, request) for row in services.conversations(request.user)])
    data = CreateConversationSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    body = data.validated_data
    if body['kind'] == Conversation.Kind.DIRECT:
        if 'user_id' not in body:
            raise services.MessagingError(400, 'user_required', 'Pick a friend to message.')
        convo = services.open_direct(request.user, body['user_id'])
    else:
        convo = services.create_group(
            request.user,
            body['kind'],
            body.get('title'),
            body.get('member_ids'),
            description=body.get('description', ''),
        )
    row = services.conversation_row(request.user, convo)
    return Response(_conversation(row, request), status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
def conversation_detail(request, conversation_id):
    """One chat; PATCH (JSON or multipart) changes a group's title,
    description or photo."""
    if request.method == 'PATCH':
        data = UpdateConversationSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        body = data.validated_data
        services.update_group(
            request.user,
            conversation_id,
            title=body.get('title'),
            description=body.get('description'),
            photo=body.get('photo'),
        )
    convo = services.membership_of(request.user, conversation_id).conversation
    row = services.conversation_row(request.user, convo)
    return Response(_conversation(row, request))


@api_view(['GET', 'POST'])
def conversation_messages(request, conversation_id):
    if request.method == 'GET':
        after = request.query_params.get('after')
        try:
            after = int(after) if after else None
        except ValueError:
            raise services.MessagingError(400, 'invalid_after', 'Bad message id.')
        rows = services.messages(request.user, conversation_id, after=after)
        return Response([_message(m, request) for m in rows])
    data = SendMessageSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    body = data.validated_data
    message = services.send_message(
        request.user,
        conversation_id,
        body.get('body', ''),
        kind=body.get('kind', 'text'),
        reply_to=body.get('reply_to'),
        payload=body.get('payload'),
        attachment=body.get('attachment'),
        allowed_reactions=body.get('allowed_reactions'),
    )
    return _fresh_message(message, request, status.HTTP_201_CREATED)


def _fresh_message(message, request, code=status.HTTP_200_OK):
    message = (
        Message.objects.select_related('sender', 'reply_to__sender')
        .prefetch_related('reactions', 'poll_votes')
        .get(pk=message.pk)
    )
    return Response(_message(message, request), status=code)


def _int(request, key):
    try:
        return int(request.data.get(key))
    except (TypeError, ValueError):
        raise services.MessagingError(400, f'invalid_{key}', f'Missing {key}.')


@api_view(['POST'])
def react(request, message_id):
    message = services.toggle_reaction(request.user, message_id, request.data.get('emoji'))
    return _fresh_message(message, request)


@api_view(['POST'])
def pin(request, message_id):
    return _fresh_message(services.toggle_pin(request.user, message_id), request)


@api_view(['POST'])
def poll_vote(request, message_id):
    message = services.vote_poll(request.user, message_id, _int(request, 'option'))
    return _fresh_message(message, request)


def _row(request, convo):
    if convo is None:
        return Response(status=status.HTTP_204_NO_CONTENT)
    try:
        row = services.conversation_row(request.user, convo)
    except services.MessagingError:
        # The caller is no longer a member (left, or the group is gone).
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(_conversation(row, request))


@api_view(['POST'])
def remove_member(request, conversation_id, user_id):
    return _row(request, services.remove_member(request.user, conversation_id, user_id))


@api_view(['POST'])
def make_heritage(request, conversation_id):
    convo = services.make_heritage(request.user, conversation_id, _int(request, 'user_id'))
    return _row(request, convo)


@api_view(['POST'])
def leave(request, conversation_id):
    pass_to = request.data.get('pass_to')
    try:
        pass_to = int(pass_to) if pass_to not in (None, '') else None
    except (TypeError, ValueError):
        raise services.MessagingError(400, 'invalid_pass_to', 'Unknown member.')
    services.leave(request.user, conversation_id, pass_to=pass_to)
    return Response(status=status.HTTP_204_NO_CONTENT)


# POST starts the creator's leave vote; DELETE cancels it.
@api_view(['POST', 'DELETE'])
def group_vote(request, conversation_id):
    if request.method == 'DELETE':
        return _row(request, services.cancel_vote(request.user, conversation_id))
    return _row(request, services.start_vote(request.user, conversation_id))


@api_view(['POST'])
def ballot(request, conversation_id):
    choice = request.data.get('choice')
    return _row(request, services.cast_ballot(request.user, conversation_id, choice))
