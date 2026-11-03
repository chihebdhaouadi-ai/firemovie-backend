from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from social.serializers import UserCardSerializer

from . import services, translation
from .errors import TakeError
from .models import Tag, Take, TakeComment


class TakeBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=280, trim_whitespace=True)
    tag = serializers.ChoiceField(choices=Tag.choices, default=Tag.REVIEW)


class CommentBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=300, trim_whitespace=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class VoteBodySerializer(serializers.Serializer):
    active = serializers.BooleanField()


class TranslateBodySerializer(serializers.Serializer):
    text = serializers.CharField(max_length=400, trim_whitespace=True)
    target_language = serializers.ChoiceField(choices=list(translation.LANGUAGE_NAMES))


@api_view(['GET'])
def film_summary(request, film_id):
    return Response(services.summary_payload(film_id, request.user))


@api_view(['PUT'])
def set_reaction(request, film_id):
    data = request.data
    if not isinstance(data, dict) or 'reaction' not in data:
        raise TakeError(400, 'invalid_reaction', 'Pick one of the reactions.')
    reaction = data['reaction']
    if reaction is not None and reaction not in services.REACTION_KEYS:
        raise TakeError(400, 'invalid_reaction', 'Pick one of the reactions.')
    services.set_reaction(film_id, request.user, reaction)
    return Response(services.summary_payload(film_id, request.user))


@api_view(['GET', 'POST'])
def film_takes(request, film_id):
    if request.method == 'GET':
        return Response(services.takes_for_film(film_id, request.user))
    serializer = TakeBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    item = services.create_take(
        film_id,
        request.user,
        serializer.validated_data['body'],
        serializer.validated_data['tag'],
    )
    return Response(item, status=201)


@api_view(['GET'])
def explore_takes(request):
    return Response(services.explore_feed(request.user))


def _take_preview(take):
    if take is None:
        return None
    return {
        'id': take.id,
        'body': take.body,
        'created_at': serializers.DateTimeField().to_representation(take.created_at),
    }


@api_view(['GET'])
def friend_activity(request, film_id):
    return Response([
        {
            'user': UserCardSerializer(row['user'], context={'request': request}).data,
            'reaction': row['reaction'],
            'take': _take_preview(row['take']),
            'updated_at': serializers.DateTimeField().to_representation(row['updated_at']),
        }
        for row in services.friend_activity_for_film(film_id, request.user)
    ])


@api_view(['PUT'])
def set_vote(request, take_id, kind):
    if kind not in services.VOTE_KINDS:
        raise TakeError(400, 'invalid_vote', 'Unknown vote.')
    take = get_object_or_404(Take.objects.select_related('author'), pk=take_id)
    if take.author_id == request.user.id:
        raise TakeError(400, 'own_take', 'You cannot vote on your own take.')
    serializer = VoteBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.set_vote(take, request.user, kind, serializer.validated_data['active'])
    return Response(services.take_item(take, request.user))


@api_view(['GET', 'POST'])
def take_comments(request, take_id):
    take = get_object_or_404(Take.objects.select_related('author'), pk=take_id)
    if request.method == 'GET':
        return Response(services.comments_for_take(take))
    serializer = CommentBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parent = None
    parent_id = serializer.validated_data.get('parent_id')
    if parent_id is not None:
        parent = TakeComment.objects.filter(pk=parent_id, take=take).first()
        if parent is None:
            raise TakeError(400, 'invalid_parent', 'That comment is no longer here.')
    item = services.create_comment(take, request.user, serializer.validated_data['body'], parent)
    return Response(item, status=201)


@api_view(['POST'])
def translate(request):
    serializer = TranslateBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = translation.translate(
        serializer.validated_data['text'],
        serializer.validated_data['target_language'],
    )
    return Response(result)
