import os

from rest_framework import serializers
from django.contrib.auth import authenticate
from films.models import FilmEntry
from films.services import counts_for, film_ids_for
from takes import reputation
from takes.models import Tag, Take
from social.services import follower_count, following_count, friendship_between
from .models import User

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _validate_image(image):
    if not image:
        return image
    if os.path.splitext(image.name)[1].lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise serializers.ValidationError('Upload a JPG, PNG or WebP image.')
    if image.size > MAX_IMAGE_BYTES:
        raise serializers.ValidationError('Image must be 5 MB or smaller.')
    header = image.read(12)
    image.seek(0)
    is_jpeg = header.startswith(b'\xff\xd8\xff')
    is_png = header.startswith(b'\x89PNG\r\n\x1a\n')
    is_webp = header[:4] == b'RIFF' and header[8:12] == b'WEBP'
    if not (is_jpeg or is_png or is_webp):
        raise serializers.ValidationError('Upload a JPG, PNG or WebP image.')
    image.content_type = 'image/jpeg' if is_jpeg else 'image/png' if is_png else 'image/webp'
    return image


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, data):
        user = next(
            (
                candidate
                for candidate in User.objects.filter(email=data['email'])
                if candidate.check_password(data['password'])
            ),
            None,
        )
        if user is None:
            raise serializers.ValidationError("Invalid credentials")
        data['user'] = user
        return data


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('bio', 'avatar', 'cover', 'equipped_frame')

    def validate_avatar(self, value):
        return _validate_image(value)

    def validate_cover(self, value):
        return _validate_image(value)


class UserSerializer(serializers.ModelSerializer):
    top_movies = serializers.SerializerMethodField()
    watched_movies = serializers.SerializerMethodField()
    watchlist_movies = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'balance', 'bio', 'avatar', 'cover',
                  'equipped_frame', 'progress',
                  'top_movies', 'watched_movies', 'watchlist_movies')

    def get_progress(self, obj):
        return reputation.progress_for(obj)

    def get_top_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.TOP_5)

    def get_watched_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.WATCHED)

    def get_watchlist_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.WATCHLIST)


class PublicProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'bio', 'avatar', 'cover', 'equipped_frame')

    def to_representation(self, obj):
        data = super().to_representation(obj)
        counts = counts_for(obj)
        data['stats'] = {
            'watched': counts[FilmEntry.ListType.WATCHED],
            'watchlist': counts[FilmEntry.ListType.WATCHLIST],
            'reviews': Take.objects.filter(author=obj, tag=Tag.REVIEW).count(),
        }
        data['progress'] = reputation.progress_for(obj)
        viewer = self.context['request'].user
        friendship, friend_request_id = friendship_between(viewer, obj)
        data['friendship'] = friendship
        data['friend_request_id'] = friend_request_id
        data['followers'] = follower_count(obj)
        data['following'] = following_count(obj)
        return data