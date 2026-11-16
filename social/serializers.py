from rest_framework import serializers

from accounts.models import User

from .models import MovieSuggestion, Notification


class UserCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'avatar')


class MovieSuggestionPayloadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MovieSuggestion
        fields = ('film_id', 'film_title', 'film_year', 'film_poster_url', 'comment')


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserCardSerializer(read_only=True)
    friend_request_id = serializers.IntegerField(read_only=True)
    suggestion = MovieSuggestionPayloadSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            'id', 'kind', 'actor', 'friend_request_id', 'suggestion', 'read', 'created_at',
        )


class FriendRequestCreateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()


class MovieSuggestionCreateSerializer(serializers.Serializer):
    film_id = serializers.CharField(min_length=1, max_length=64)
    film_title = serializers.CharField(min_length=1, max_length=255)
    film_year = serializers.IntegerField(
        required=False, allow_null=True, min_value=0, max_value=9999,
    )
    film_poster_url = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=500,
    )
    comment = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=280,
    )
    recipient_ids = serializers.ListField(
        child=serializers.IntegerField(), min_length=1, max_length=50,
    )

    def validate_recipient_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError('Recipient ids must be unique.')
        return value
