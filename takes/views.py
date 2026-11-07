from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from social.serializers import UserCardSerializer

from . import reputation, services, translation
from .errors import TakeError
from .models import TOPIC_VOTE_KINDS, Tag, Take, TakeComment


class TakeBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=280, trim_whitespace=True)
    tag = serializers.ChoiceField(choices=Tag.choices, default=Tag.REVIEW)


MAX_TOPIC_IMAGE_BYTES = 5 * 1024 * 1024
TOPIC_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


class TopicSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=280, trim_whitespace=True)
    tag = serializers.ChoiceField(choices=[Tag.QUESTION, Tag.DISCUSSION])
    film_id = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    image = serializers.FileField(required=False, allow_null=True, default=None)

    def validate_image(self, image):
        if image is None:
            return None
        if image.content_type not in TOPIC_IMAGE_TYPES:
            raise serializers.ValidationError('Use a JPEG, PNG or WebP photo.', code='invalid_image')
        if image.size > MAX_TOPIC_IMAGE_BYTES:
            raise serializers.ValidationError('Photos must be 5 MB or smaller.', code='image_too_large')
        return image

    def validate(self, data):
        if not data['film_id'] and data.get('image') is None:
            raise serializers.ValidationError(
                'Choose a movie or add a photo to your topic.', code='topic_needs_subject'
            )
        return data


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


def _first_error(errors):
    """Flatten serializer errors into the TakeError shape the apps read."""
    for value in errors.values():
        detail = value[0] if isinstance(value, list) else value
        message = detail.get('message') if isinstance(detail, dict) else detail
        code = getattr(detail, 'code', 'invalid')
        return TakeError(400, code, str(message))
    return TakeError(400, 'invalid', 'Check your topic and try again.')


@api_view(['POST'])
def create_topic(request):
    serializer = TopicSerializer(data=request.data)
    if not serializer.is_valid():
        raise _first_error(serializer.errors)
    data = serializer.validated_data
    item = services.create_topic(
        request.user,
        data['body'],
        data['tag'],
        film_id=data['film_id'],
        image=data.get('image'),
    )
    return Response(item, status=201)


@api_view(['GET'])
def explore_takes(request):
    return Response(services.explore_feed(request.user))


@api_view(['GET'])
def trending_topics(request):
    return Response(services.trending_topics(request.user))


@api_view(['GET'])
def friend_takes(request):
    return Response(services.friend_takes(request.user))


@api_view(['GET'])
def my_takes(request):
    return Response(services.my_takes(request.user))


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
    if kind in TOPIC_VOTE_KINDS and take.tag == Tag.REVIEW:
        raise TakeError(400, 'invalid_vote', 'Likes are only for questions and discussions.')
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


@api_view(['GET'])
def leaderboard(request):
    period = request.query_params.get('period', 'week')
    return Response(reputation.leaderboard_payload(request.user, period, request))


@api_view(['POST'])
def translate(request):
    serializer = TranslateBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    result = translation.translate(
        serializer.validated_data['text'],
        serializer.validated_data['target_language'],
    )
    return Response(result)
