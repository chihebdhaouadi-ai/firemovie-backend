from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from social.serializers import UserCardSerializer

from . import reputation, services, translation
from .errors import TakeError
from .models import MAX_REACTIONS_PER_FILM, CardSkin, CommentStance, ReportReason, REVIEW_VOTE_KINDS, TOPIC_VOTE_KINDS, Tag, Take, TakeComment


# Film takes can run long (reviews); topics stay short.
MAX_TAKE_LENGTH = 1500


class TakeBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=MAX_TAKE_LENGTH, trim_whitespace=True)
    tag = serializers.ChoiceField(choices=Tag.choices, default=Tag.REVIEW)
    skin = serializers.ChoiceField(choices=CardSkin.choices, default=CardSkin.NORMAL)
    spoiler = serializers.BooleanField(required=False, default=False)


MAX_TOPIC_IMAGE_BYTES = 5 * 1024 * 1024
TOPIC_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


MAX_POLL_OPTIONS = 4
MIN_POLL_OPTIONS = 2


class TopicSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=280, trim_whitespace=True)
    tag = serializers.ChoiceField(choices=[Tag.QUESTION, Tag.DISCUSSION, Tag.HOT_TAKE, Tag.POLL, Tag.SCENE])
    film_id = serializers.CharField(max_length=20, required=False, allow_blank=True, default='')
    image = serializers.FileField(required=False, allow_null=True, default=None)
    options = serializers.ListField(
        child=serializers.CharField(max_length=80, trim_whitespace=True, allow_blank=True),
        max_length=MAX_POLL_OPTIONS,
        required=False,
        default=list,
    )
    scene = serializers.CharField(max_length=120, required=False, allow_blank=True, default='', trim_whitespace=True)
    timecode = serializers.CharField(max_length=20, required=False, allow_blank=True, default='', trim_whitespace=True)
    spoiler = serializers.BooleanField(required=False, default=False)
    skin = serializers.ChoiceField(choices=CardSkin.choices, required=False, default=CardSkin.NORMAL)

    def validate_image(self, image):
        if image is None:
            return None
        if image.content_type not in TOPIC_IMAGE_TYPES:
            raise serializers.ValidationError('Use a JPEG, PNG or WebP photo.', code='invalid_image')
        if image.size > MAX_TOPIC_IMAGE_BYTES:
            raise serializers.ValidationError('Photos must be 5 MB or smaller.', code='image_too_large')
        return image

    def validate(self, data):
        tag = data['tag']
        if tag == Tag.POLL:
            options = [option for option in data['options'] if option]
            if not MIN_POLL_OPTIONS <= len(options) <= MAX_POLL_OPTIONS:
                raise serializers.ValidationError(
                    'Add 2 to 4 options to your poll.', code='poll_options_invalid'
                )
            if len({option.lower() for option in options}) != len(options):
                raise serializers.ValidationError(
                    'Each poll option must be different.', code='poll_options_invalid'
                )
            data['options'] = options
            # Polls are about the question, not a film or a photo.
            data['film_id'] = data['film_id'] or ''
            data['image'] = None
            return data

        data['options'] = []
        if tag == Tag.SCENE:
            if not data['film_id']:
                raise serializers.ValidationError('Choose the movie this scene is from.', code='scene_needs_film')
            if not data['scene']:
                raise serializers.ValidationError('Name the scene you are talking about.', code='scene_required')
            return data

        data['scene'] = ''
        data['timecode'] = ''
        if not data['film_id'] and data.get('image') is None:
            raise serializers.ValidationError(
                'Choose a movie or add a photo to your topic.', code='topic_needs_subject'
            )
        return data


class CommentBodySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=300, trim_whitespace=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    stance = serializers.ChoiceField(
        choices=CommentStance.choices,
        required=False,
        allow_null=True,
        default=None,
    )


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
    """Body {"reactions": [...]} with up to 3 feelings (empty clears them), or the older
    single form {"reaction": "loved" | null}."""
    data = request.data
    invalid = TakeError(400, 'invalid_reaction', 'Pick up to 3 of the reactions.')
    if not isinstance(data, dict):
        raise invalid
    if 'reactions' in data:
        reactions = data['reactions']
        if not isinstance(reactions, list) or len(set(map(str, reactions))) != len(reactions):
            raise invalid
    elif 'reaction' in data:
        reactions = [] if data['reaction'] is None else [data['reaction']]
    else:
        raise invalid
    if len(reactions) > MAX_REACTIONS_PER_FILM or any(
        reaction not in services.REACTION_KEYS for reaction in reactions
    ):
        raise invalid
    services.set_reactions(film_id, request.user, reactions)
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
        skin=serializer.validated_data['skin'],
        spoiler=serializer.validated_data['spoiler'],
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
        options=data['options'],
        scene=data['scene'],
        timecode=data['timecode'],
        spoiler=data['spoiler'],
        skin=data['skin'],
    )
    return Response(item, status=201)


# Topics keep the shorter limit they were posted with.
MAX_TOPIC_LENGTH = 280


class EditTakeSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=MAX_TAKE_LENGTH, trim_whitespace=True)
    skin = serializers.ChoiceField(choices=CardSkin.choices, required=False)
    spoiler = serializers.BooleanField(required=False)


class ReportTakeSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReportReason.choices)
    details = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default='', trim_whitespace=True,
    )


class ShareTakeSerializer(serializers.Serializer):
    recipient_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=services.MAX_SHARE_RECIPIENTS,
    )
    message = serializers.CharField(
        max_length=280, required=False, allow_blank=True, default='', trim_whitespace=True,
    )


@api_view(['GET', 'PATCH', 'DELETE'])
def take_detail(request, take_id):
    take = get_object_or_404(Take.objects.select_related('author'), pk=take_id)
    if request.method == 'GET':
        return Response(services.take_detail(take, request.user))
    if take.author_id != request.user.id:
        raise TakeError(403, 'not_owner', 'Only the author can change this take.')
    if request.method == 'DELETE':
        take.delete()
        return Response(status=204)
    serializer = EditTakeSerializer(data=request.data)
    if not serializer.is_valid():
        raise _first_error(serializer.errors)
    body = serializer.validated_data['body']
    if take.tag != Tag.REVIEW and len(body) > MAX_TOPIC_LENGTH:
        raise TakeError(400, 'max_length', f'Topics can be up to {MAX_TOPIC_LENGTH} characters.')
    services.edit_take(
        take,
        body,
        serializer.validated_data.get('skin'),
        spoiler=serializer.validated_data.get('spoiler'),
    )
    return Response(services.take_detail(take, request.user))


@api_view(['POST'])
def report_take(request, take_id):
    take = get_object_or_404(Take, pk=take_id)
    if take.author_id == request.user.id:
        raise TakeError(400, 'own_take', 'You cannot report your own take.')
    serializer = ReportTakeSerializer(data=request.data)
    if not serializer.is_valid():
        raise _first_error(serializer.errors)
    created = services.report_take(
        take,
        request.user,
        serializer.validated_data['reason'],
        serializer.validated_data['details'],
    )
    return Response({'reported': True}, status=201 if created else 200)


@api_view(['POST'])
def share_take(request, take_id):
    take = get_object_or_404(Take, pk=take_id)
    serializer = ShareTakeSerializer(data=request.data)
    if not serializer.is_valid():
        raise _first_error(serializer.errors)
    sent = services.share_take(
        take,
        request.user,
        serializer.validated_data['recipient_ids'],
        serializer.validated_data['message'],
    )
    return Response({'sent': sent}, status=201)


class PollVoteSerializer(serializers.Serializer):
    option_id = serializers.IntegerField(min_value=1)


@api_view(['POST'])
def vote_poll(request, take_id):
    take = get_object_or_404(Take.objects.select_related('author'), pk=take_id)
    serializer = PollVoteSerializer(data=request.data)
    if not serializer.is_valid():
        raise _first_error(serializer.errors)
    item = services.vote_poll(take, request.user, serializer.validated_data['option_id'])
    return Response(item)


@api_view(['GET'])
def explore_takes(request):
    return Response(services.explore_feed(request.user))


@api_view(['GET'])
def top_takes(request):
    tag = request.query_params.get('tag') or None
    if tag is not None and tag not in Tag.values:
        raise TakeError(400, 'invalid_tag', 'Unknown take tag.')
    return Response(services.top_takes(request.user, tag=tag))


@api_view(['GET'])
def trending_topics(request):
    return Response(services.trending_topics(request.user))


@api_view(['GET'])
def friend_takes(request):
    return Response(services.friend_takes(request.user))


@api_view(['GET'])
def friend_stories(request):
    when = serializers.DateTimeField()
    return Response([
        {
            'user': UserCardSerializer(group['user'], context={'request': request}).data,
            'latest_at': when.to_representation(group['latest_at']),
            'items': [
                {**item, 'created_at': when.to_representation(item['created_at'])}
                for item in group['items']
            ],
        }
        for group in services.friend_stories(request.user)
    ])


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
    if kind in REVIEW_VOTE_KINDS and take.tag != Tag.REVIEW:
        raise TakeError(400, 'invalid_vote', 'Up, draw and down are only for reviews.')
    serializer = VoteBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.set_vote(take, request.user, kind, serializer.validated_data['active'])
    return Response(services.take_item(take, request.user))


@api_view(['PUT'])
def set_comment_vote(request, comment_id, kind):
    if kind not in services.COMMENT_VOTE_KINDS:
        raise TakeError(400, 'invalid_vote', 'Unknown vote.')
    comment = get_object_or_404(TakeComment.objects.select_related('take', 'author'), pk=comment_id)
    if comment.author_id == request.user.id:
        raise TakeError(400, 'own_comment', 'You cannot vote on your own comment.')
    serializer = VoteBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.set_comment_vote(comment, request.user, kind, serializer.validated_data['active'])
    return Response(services.comment_item(comment, comment.take, request.user))


@api_view(['GET', 'POST'])
def take_comments(request, take_id):
    take = get_object_or_404(Take.objects.select_related('author'), pk=take_id)
    if request.method == 'GET':
        return Response(services.comments_for_take(take, request.user))
    serializer = CommentBodySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    parent = None
    parent_id = serializer.validated_data.get('parent_id')
    if parent_id is not None:
        parent = TakeComment.objects.filter(pk=parent_id, take=take).first()
        if parent is None:
            raise TakeError(400, 'invalid_parent', 'That comment is no longer here.')
    stance = serializer.validated_data.get('stance')
    if stance is not None and (take.tag != Tag.REVIEW or parent is not None):
        raise TakeError(
            400,
            'invalid_stance',
            'Stances are only allowed on top-level comments on reviews.',
        )
    if stance is not None and take.author_id == request.user.id:
        raise TakeError(400, 'own_take', 'You cannot vote on your own take.')
    item = services.create_comment(
        take,
        request.user,
        serializer.validated_data['body'],
        parent,
        stance=stance,
    )
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
