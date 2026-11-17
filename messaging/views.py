from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from social.serializers import UserCardSerializer

from . import services
from .models import Conversation

_when = serializers.DateTimeField()


def _user(user, request):
    return UserCardSerializer(user, context={'request': request}).data


def _message(message, request):
    return {
        'id': message.id,
        'body': message.body,
        'sender': _user(message.sender, request),
        'created_at': _when.to_representation(message.created_at),
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


class SendMessageSerializer(serializers.Serializer):
    body = serializers.CharField(allow_blank=True, trim_whitespace=False)


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
            request.user, body['kind'], body.get('title'), body.get('member_ids')
        )
    row = services.conversation_row(request.user, convo)
    return Response(_conversation(row, request), status=status.HTTP_201_CREATED)


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
    message = services.send_message(request.user, conversation_id, data.validated_data['body'])
    return Response(_message(message, request), status=status.HTTP_201_CREATED)
