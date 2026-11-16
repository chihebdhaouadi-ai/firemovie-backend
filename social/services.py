from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from accounts.models import User

from .models import FriendRequest, Follow, MovieSuggestion, Notification


class NotFriends(APIException):
    status_code = 400
    default_detail = 'You can only send suggestions to your friends.'
    default_code = 'not_friends'


class SelfFriendRequest(APIException):
    status_code = 400
    default_detail = "You can't send a friend request to yourself."
    default_code = 'self_friend_request'


class AlreadyConnected(APIException):
    status_code = 400
    default_detail = 'You are already connected or a request is pending.'
    default_code = 'already_connected'


def _between(a, b):
    return Q(sender=a, receiver=b) | Q(sender=b, receiver=a)


def friendship_between(viewer, target):
    if viewer.pk == target.pk:
        return 'self', None
    request = FriendRequest.objects.filter(_between(viewer, target)).first()
    if request is None:
        return 'none', None
    if request.status == FriendRequest.Status.ACCEPTED:
        return 'friends', None
    if request.sender_id == viewer.pk:
        return 'outgoing', None
    return 'incoming', request.pk


@transaction.atomic
def send_friend_request(sender, receiver):
    if sender.pk == receiver.pk:
        raise SelfFriendRequest()
    if FriendRequest.objects.filter(_between(sender, receiver)).exists():
        raise AlreadyConnected()
    friend_request = FriendRequest.objects.create(sender=sender, receiver=receiver)
    Follow.objects.get_or_create(follower=sender, following=receiver)
    Notification.objects.create(
        recipient=receiver,
        actor=sender,
        kind=Notification.Kind.FRIEND_REQUEST,
        friend_request=friend_request,
    )
    return friend_request


@transaction.atomic
def accept_friend_request(friend_request):
    friend_request.status = FriendRequest.Status.ACCEPTED
    friend_request.responded_at = timezone.now()
    friend_request.save(update_fields=['status', 'responded_at'])
    Follow.objects.get_or_create(
        follower=friend_request.receiver, following=friend_request.sender,
    )
    Notification.objects.create(
        recipient=friend_request.sender,
        actor=friend_request.receiver,
        kind=Notification.Kind.FRIEND_ACCEPTED,
    )


@transaction.atomic
def remove_friend_request(friend_request):
    Follow.objects.filter(
        follower=friend_request.sender, following=friend_request.receiver,
    ).delete()
    friend_request.delete()


@transaction.atomic
def send_movie_suggestions(sender, recipient_ids, *, film_id, film_title, film_year,
                           film_poster_url, comment):
    recipients = list(User.objects.filter(pk__in=recipient_ids))
    if len(recipients) != len(set(recipient_ids)):
        raise NotFriends()
    for recipient in recipients:
        if friendship_between(sender, recipient)[0] != 'friends':
            raise NotFriends()
    for recipient in recipients:
        suggestion = MovieSuggestion.objects.create(
            sender=sender,
            recipient=recipient,
            film_id=film_id,
            film_title=film_title,
            film_year=film_year,
            film_poster_url=film_poster_url,
            comment=comment,
        )
        Notification.objects.create(
            recipient=recipient,
            actor=sender,
            kind=Notification.Kind.MOVIE_SUGGESTION,
            suggestion=suggestion,
        )
    return len(recipients)


def follower_count(user):
    return Follow.objects.filter(following=user).count()


def following_count(user):
    return Follow.objects.filter(follower=user).count()
