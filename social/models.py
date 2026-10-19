from django.conf import settings
from django.db import models


class Follow(models.Model):
    follower = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following_links',
    )
    following = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='follower_links',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')


class FriendRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        ACCEPTED = 'accepted', 'Accepted'

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_friend_requests',
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_friend_requests',
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('sender', 'receiver')


class MovieSuggestion(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_movie_suggestions',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_movie_suggestions',
    )
    film_id = models.CharField(max_length=64)
    film_title = models.CharField(max_length=255)
    film_year = models.PositiveSmallIntegerField(null=True, blank=True)
    film_poster_url = models.CharField(max_length=500, blank=True)
    comment = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Notification(models.Model):
    class Kind(models.TextChoices):
        FRIEND_REQUEST = 'friend_request', 'Friend request'
        FRIEND_ACCEPTED = 'friend_accepted', 'Friend request accepted'
        MOVIE_SUGGESTION = 'movie_suggestion', 'Movie suggestion'

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+',
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    friend_request = models.ForeignKey(
        FriendRequest, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications',
    )
    suggestion = models.ForeignKey(
        MovieSuggestion, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications',
    )
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')
