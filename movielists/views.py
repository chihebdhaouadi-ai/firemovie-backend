from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from films.movie_source import IMDB_ID_PATTERN
from takes.errors import TakeError
from takes.views import MAX_TOPIC_IMAGE_BYTES, TOPIC_IMAGE_TYPES

from . import services
from .models import MAX_COMMENT_LENGTH, MAX_FILMS, MAX_NAME_LENGTH, MovieList, MovieListComment


class FilmSerializer(serializers.Serializer):
    film_id = serializers.CharField(max_length=20)
    title = serializers.CharField(max_length=255)
    poster_url = serializers.URLField(max_length=500, required=False, allow_blank=True, allow_null=True)

    def validate_film_id(self, value):
        if IMDB_ID_PATTERN.fullmatch(value) is None:
            raise serializers.ValidationError('Not an IMDb id.')
        return value


class ListBodySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=MAX_NAME_LENGTH, trim_whitespace=True)
    films = FilmSerializer(many=True)

    def validate_films(self, films):
        if not films:
            raise serializers.ValidationError('Add at least one film.')
        if len(films) > MAX_FILMS:
            raise serializers.ValidationError(f'A list holds at most {MAX_FILMS} films.')
        seen, unique = set(), []
        for film in films:
            if film['film_id'] not in seen:
                seen.add(film['film_id'])
                unique.append(film)
        return unique


class ListPatchSerializer(ListBodySerializer):
    name = serializers.CharField(max_length=MAX_NAME_LENGTH, trim_whitespace=True, required=False)
    films = FilmSerializer(many=True, required=False)


class LikeSerializer(serializers.Serializer):
    active = serializers.BooleanField()


class ShareSerializer(serializers.Serializer):
    recipient_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=20,
    )
    message = serializers.CharField(
        max_length=280, required=False, allow_blank=True, default='', trim_whitespace=True,
    )


class CommentSerializer(serializers.Serializer):
    body = serializers.CharField(
        max_length=MAX_COMMENT_LENGTH, trim_whitespace=True, required=False, allow_blank=True, default='',
    )
    image = serializers.FileField(required=False, allow_null=True, default=None)
    parent_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_image(self, image):
        if image is None:
            return None
        if image.content_type not in TOPIC_IMAGE_TYPES:
            raise serializers.ValidationError('Use a JPEG, PNG or WebP photo.', code='invalid_image')
        if image.size > MAX_TOPIC_IMAGE_BYTES:
            raise serializers.ValidationError('Photos must be 5 MB or smaller.', code='image_too_large')
        return image

    def validate(self, data):
        if not data.get('body') and data.get('image') is None:
            raise serializers.ValidationError('Write something or add a photo.', code='empty_comment')
        return data


def _find(list_id, viewer):
    movie_list = services.get_list(list_id, viewer)
    if movie_list is None:
        raise TakeError(404, 'not_found', 'This list does not exist.')
    return movie_list


def _own(movie_list, viewer):
    if movie_list.owner_id != viewer.id:
        raise TakeError(403, 'not_owner', 'Only the owner can change this list.')


@api_view(['GET', 'POST'])
def lists(request):
    """Your lists, newest first; POST posts a new one."""
    if request.method == 'POST':
        body = ListBodySerializer(data=request.data)
        body.is_valid(raise_exception=True)
        created = services.create_list(request.user, body.validated_data['name'], body.validated_data['films'])
        movie_list = _find(created.id, request.user)
        return Response(services.list_detail(movie_list, request.user, request), status=status.HTTP_201_CREATED)
    return Response({
        'data': [services.list_item(item, request.user, request) for item in services.my_lists(request.user)],
    })


@api_view(['GET'])
def friends_lists(request):
    """Lists your friends posted, newest first."""
    return Response({
        'data': [services.list_item(item, request.user, request) for item in services.friends_lists(request.user)],
    })


@api_view(['GET', 'PATCH', 'DELETE'])
def list_detail(request, list_id):
    movie_list = _find(list_id, request.user)
    if request.method == 'DELETE':
        _own(movie_list, request.user)
        movie_list.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if request.method == 'PATCH':
        _own(movie_list, request.user)
        body = ListPatchSerializer(data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        services.update_list(movie_list, body.validated_data.get('name'), body.validated_data.get('films'))
        movie_list = _find(list_id, request.user)
    return Response(services.list_detail(movie_list, request.user, request))


@api_view(['PUT'])
def like(request, list_id):
    """A heart on a list, your own included."""
    movie_list = get_object_or_404(MovieList, pk=list_id)
    body = LikeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    services.set_like(movie_list, request.user, body.validated_data['active'])
    return Response(services.list_item(_find(list_id, request.user), request.user, request))


@api_view(['PUT'])
def save(request, list_id):
    """Keep someone's list on your profile; your own is already yours."""
    movie_list = get_object_or_404(MovieList, pk=list_id)
    if movie_list.owner_id == request.user.id:
        raise TakeError(400, 'own_list', 'You cannot save your own list.')
    body = LikeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    services.set_saved(movie_list, request.user, body.validated_data['active'])
    return Response(services.list_item(_find(list_id, request.user), request.user, request))


@api_view(['POST'])
def share(request, list_id):
    """Sends the list into your chat with each friend picked."""
    movie_list = _find(list_id, request.user)
    body = ShareSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    sent = services.share_list(
        movie_list, request.user, body.validated_data['recipient_ids'],
        body.validated_data['message'], request,
    )
    return Response({'sent': sent}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def saved_lists(request):
    """Lists you saved, newest save first."""
    return Response({
        'data': [services.list_item(item, request.user, request) for item in services.saved_lists(request.user)],
    })


@api_view(['GET', 'POST'])
def comments(request, list_id):
    movie_list = get_object_or_404(MovieList, pk=list_id)
    if request.method == 'POST':
        body = CommentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        parent = None
        parent_id = body.validated_data.get('parent_id')
        if parent_id is not None:
            parent = MovieListComment.objects.filter(pk=parent_id, movie_list=movie_list).first()
            if parent is None:
                raise TakeError(400, 'invalid_parent', 'That comment is no longer here.')
        comment = services.add_comment(
            movie_list,
            request.user,
            body.validated_data['body'],
            parent=parent,
            image=body.validated_data.get('image'),
        )
        return Response(
            services.comment_item(comment, request, viewer=request.user),
            status=status.HTTP_201_CREATED,
        )
    return Response({
        'data': [
            services.comment_item(c, request, viewer=request.user)
            for c in services.comments_of(movie_list)
        ],
    })
