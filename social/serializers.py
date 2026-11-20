from rest_framework import serializers

from accounts.models import User

from .models import FriendRequest, MovieSuggestion, Notification


class UserCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'avatar', 'equipped_frame')


class MovieSuggestionPayloadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MovieSuggestion
        fields = ('film_id', 'film_title', 'film_year', 'film_poster_url', 'comment')


TAKE_PREVIEW_LENGTH = 140


class NotificationSerializer(serializers.ModelSerializer):
    actor = UserCardSerializer(read_only=True)
    friend_request_id = serializers.SerializerMethodField()
    suggestion = MovieSuggestionPayloadSerializer(read_only=True)
    take = serializers.SerializerMethodField()
    comment_id = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            'id', 'kind', 'actor', 'friend_request_id', 'suggestion', 'take', 'comment_id',
            'message', 'read', 'created_at',
        )

    def get_friend_request_id(self, notification):
        """The request to answer, only while it still waits for an answer;
        once accepted the row no longer offers Accept and Decline."""
        friend_request = notification.friend_request
        if friend_request is None or friend_request.status != FriendRequest.Status.PENDING:
            return None
        return friend_request.id

    def get_take(self, notification):
        """Where a share or mention leads: enough to open the take's page."""
        take = notification.take
        if take is None:
            return None
        return {
            'id': take.id,
            'film_id': take.film_id,
            'tag': take.tag,
            'body': take.body[:TAKE_PREVIEW_LENGTH],
            'spoiler': take.spoiler,
        }


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
