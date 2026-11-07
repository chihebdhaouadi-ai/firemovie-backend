from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import serializers

from films.catalog import try_stored_film
from social.models import FriendRequest

from .errors import TakeError
from films.models import Film

from .models import FilmReaction, Reaction, Tag, Take, TakeComment, TakeCommentVote, TakeVote, VoteKind

REACTION_KEYS = [choice.value for choice in Reaction]
VOTE_KINDS = [choice.value for choice in VoteKind]
COMMENT_VOTE_KINDS = [VoteKind.LIKE, VoteKind.DISLIKE]
TAG_KEYS = [choice.value for choice in Tag]
EXPLORE_LIMIT = 30
TRENDING_LIMIT = 10
FRIEND_TAKES_LIMIT = 20
TRENDING_WINDOW = timedelta(days=7)
POSITIVE = {'loved', 'blew_mind', 'made_think', 'made_laugh', 'masterpiece'}
NEGATIVE = {'broke_heart', 'bored', 'disappointed'}
MAX_WELL_ARGUED_BONUS = 10
TRUST_STEP = 0.1


def _percent(part, whole):
    if whole == 0:
        return None
    return round(100 * part / whole)


def _trust_weights(user_ids):
    if not user_ids:
        return {}
    rows = (
        TakeVote.objects.filter(kind=VoteKind.WELL_ARGUED, take__author_id__in=user_ids)
        .values('take__author_id')
        .annotate(total=Count('id'))
    )
    received = {row['take__author_id']: row['total'] for row in rows}
    return {
        user_id: 1 + TRUST_STEP * min(received.get(user_id, 0), MAX_WELL_ARGUED_BONUS)
        for user_id in user_ids
    }


def summary_payload(film_id, viewer):
    reactions = list(
        FilmReaction.objects.filter(film_id=film_id).values_list('user_id', 'reaction')
    )
    counts = {key: 0 for key in REACTION_KEYS}
    for _, reaction in reactions:
        counts[reaction] += 1

    positive = [user_id for user_id, reaction in reactions if reaction in POSITIVE]
    negative = [user_id for user_id, reaction in reactions if reaction in NEGATIVE]
    weights = _trust_weights(set(positive) | set(negative))
    weighted_positive = sum(weights[user_id] for user_id in positive)
    weighted_negative = sum(weights[user_id] for user_id in negative)

    most_felt = sorted(
        ((key, count) for key, count in counts.items() if count > 0),
        key=lambda item: (-item[1], REACTION_KEYS.index(item[0])),
    )[:3]
    my_reaction = next((reaction for user_id, reaction in reactions if user_id == viewer.id), None)

    return {
        'film_id': film_id,
        'total': len(reactions),
        'counts': counts,
        'my_reaction': my_reaction,
        'most_felt': [{'reaction': key, 'count': count} for key, count in most_felt],
        'everyone_percent': _percent(len(positive), len(positive) + len(negative)),
        'trusted_percent': _percent(weighted_positive, weighted_positive + weighted_negative),
    }


def set_reaction(film_id, user, reaction):
    with transaction.atomic():
        if reaction is None:
            FilmReaction.objects.filter(film_id=film_id, user=user).delete()
            return
        FilmReaction.objects.update_or_create(
            film_id=film_id, user=user, defaults={'reaction': reaction}
        )
        Take.objects.filter(film_id=film_id, author=user, tag=Tag.REVIEW).update(reaction=reaction)


def _item(take, viewer, is_most_helpful=False):
    counts = {kind: 0 for kind in VOTE_KINDS}
    my_votes = []
    for vote in take.votes.all():
        counts[vote.kind] += 1
        if vote.user_id == viewer.id:
            my_votes.append(vote.kind)
    comment_count = getattr(take, 'comment_total', None)
    if comment_count is None:
        comment_count = take.comments.count()
    return {
        'id': take.id,
        'film_id': take.film_id,
        'author_id': take.author_id,
        'author_name': take.author.username,
        'author_avatar': take.author.avatar.url if take.author.avatar else None,
        'is_mine': take.author_id == viewer.id,
        'reaction': take.reaction,
        'tag': take.tag,
        'body': take.body,
        'image_url': take.image.url if take.image else None,
        'created_at': serializers.DateTimeField().to_representation(take.created_at),
        'votes': counts,
        'my_votes': my_votes,
        'comment_count': comment_count,
        'is_most_helpful': is_most_helpful,
    }


def takes_for_film(film_id, viewer):
    takes = list(
        Take.objects.filter(film_id=film_id)
        .select_related('author')
        .prefetch_related('votes')
        .annotate(comment_total=Count('comments'))
    )

    def helpfulness(take):
        return sum(1 for vote in take.votes.all() if vote.kind in (VoteKind.WELL_ARGUED, VoteKind.CHANGED_MY_MIND))

    ranked = sorted(takes, key=lambda take: (helpfulness(take), take.created_at, take.id), reverse=True)
    items = []
    for index, take in enumerate(ranked):
        is_most_helpful = (
            index == 0 and helpfulness(take) > 0 and take.author_id != viewer.id
        )
        items.append(_item(take, viewer, is_most_helpful=is_most_helpful))
    return items


def take_item(take, viewer):
    return next(item for item in takes_for_film(take.film_id, viewer) if item['id'] == take.id)


def create_take(film_id, user, body, tag=Tag.REVIEW):
    reaction = None
    if tag == Tag.REVIEW:
        reaction = (
            FilmReaction.objects.filter(film_id=film_id, user=user)
            .values_list('reaction', flat=True)
            .first()
        )
        if reaction is None:
            raise TakeError(400, 'reaction_required', 'Pick a reaction before sharing a take.')
        if Take.objects.filter(film_id=film_id, author=user, tag=Tag.REVIEW).exists():
            raise TakeError(409, 'already_posted', 'You already shared a take for this film.')
    try:
        with transaction.atomic():
            take = Take.objects.create(
                film_id=film_id, author=user, reaction=reaction, tag=tag, body=body
            )
    except IntegrityError:
        raise TakeError(409, 'already_posted', 'You already shared a take for this film.')
    try_stored_film(film_id)
    return _item(take, user)


def set_vote(take, user, kind, active):
    if active:
        TakeVote.objects.get_or_create(take=take, user=user, kind=kind)
    else:
        TakeVote.objects.filter(take=take, user=user, kind=kind).delete()


def comment_item(comment, take, viewer):
    likes = dislikes = 0
    my_vote = None
    for vote in comment.votes.all():
        if vote.kind == VoteKind.LIKE:
            likes += 1
        else:
            dislikes += 1
        if vote.user_id == viewer.id:
            my_vote = vote.kind
    return {
        'id': comment.id,
        'author_id': comment.author_id,
        'author_name': comment.author.username,
        'parent_id': comment.parent_id,
        'body': comment.body,
        'created_at': serializers.DateTimeField().to_representation(comment.created_at),
        'is_writer': comment.author_id == take.author_id,
        'is_mine': comment.author_id == viewer.id,
        'likes': likes,
        'dislikes': dislikes,
        'my_vote': my_vote,
    }


def comments_for_take(take, viewer):
    comments = (
        TakeComment.objects.filter(take=take)
        .select_related('author')
        .prefetch_related('votes')
        .order_by('created_at', 'id')
    )
    return [comment_item(comment, take, viewer) for comment in comments]


def create_comment(take, user, body, parent=None):
    comment = TakeComment.objects.create(take=take, author=user, body=body, parent=parent)
    return comment_item(comment, take, user)


def set_comment_vote(comment, user, kind, active):
    """Like or dislike a comment. Choosing one replaces the other."""
    with transaction.atomic():
        if active:
            TakeCommentVote.objects.filter(comment=comment, user=user).exclude(kind=kind).delete()
            TakeCommentVote.objects.update_or_create(
                comment=comment, user=user, defaults={'kind': kind}
            )
        else:
            TakeCommentVote.objects.filter(comment=comment, user=user, kind=kind).delete()


def friend_ids(user):
    links = (
        FriendRequest.objects.filter(status=FriendRequest.Status.ACCEPTED)
        .filter(Q(sender=user) | Q(receiver=user))
        .values_list('sender_id', 'receiver_id')
    )
    return {receiver if sender == user.id else sender for sender, receiver in links}


def friend_activity_for_film(film_id, viewer):
    ids = friend_ids(viewer)
    if not ids:
        return []
    reactions = list(
        FilmReaction.objects.filter(film_id=film_id, user_id__in=ids).select_related('user')
    )
    takes = {
        take.author_id: take
        for take in Take.objects.filter(film_id=film_id, author_id__in=ids, tag=Tag.REVIEW)
    }
    rows = []
    for reaction in reactions:
        take = takes.get(reaction.user_id)
        updated_at = reaction.updated_at
        if take is not None and take.created_at > updated_at:
            updated_at = take.created_at
        rows.append({
            'user': reaction.user,
            'reaction': reaction.reaction,
            'take': take,
            'updated_at': updated_at,
        })
    rows.sort(key=lambda row: row['updated_at'], reverse=True)
    return rows


def create_topic(user, body, tag, film_id='', image=None):
    """A question or discussion, optionally about a film and/or with a photo."""
    try:
        with transaction.atomic():
            take = Take.objects.create(
                film_id=film_id or '', author=user, reaction=None, tag=tag,
                body=body, image=image or None,
            )
    except IntegrityError:
        raise TakeError(409, 'already_posted', 'Could not save your topic.')
    if film_id:
        try_stored_film(film_id)
    return _item(take, user)


def _feed_items(takes, viewer):
    films = {
        film.imdb_id: film
        for film in Film.objects.filter(imdb_id__in={take.film_id for take in takes})
    }
    items = []
    for take in takes:
        film = films.get(take.film_id)
        item = _item(take, viewer)
        item['film'] = {
            'film_id': take.film_id,
            'title': (film.title or None) if film else None,
            'poster_url': film.poster_url if film else None,
        }
        items.append(item)
    return items


def explore_feed(viewer, limit=EXPLORE_LIMIT):
    """Newest takes, questions and discussions across every film."""
    takes = list(
        Take.objects.select_related('author')
        .prefetch_related('votes')
        .annotate(comment_total=Count('comments'))
        .order_by('-created_at', '-id')[:limit]
    )
    return _feed_items(takes, viewer)


def trending_topics(viewer, limit=TRENDING_LIMIT):
    """Questions and discussions from the last week, ranked by replies and votes."""
    since = timezone.now() - TRENDING_WINDOW
    takes = list(
        Take.objects.select_related('author')
        .prefetch_related('votes')
        .filter(tag__in=[Tag.QUESTION, Tag.DISCUSSION], created_at__gte=since)
        .annotate(
            comment_total=Count('comments', distinct=True),
            vote_total=Count('votes', distinct=True),
        )
        .annotate(engagement=F('comment_total') * 2 + F('vote_total'))
        .order_by('-engagement', '-created_at', '-id')[:limit]
    )
    return _feed_items(takes, viewer)


def friend_takes(viewer, limit=FRIEND_TAKES_LIMIT):
    """Newest reviews written by accepted friends, across every film."""
    ids = friend_ids(viewer)
    if not ids:
        return []
    takes = list(
        Take.objects.select_related('author')
        .prefetch_related('votes')
        .filter(author_id__in=ids, tag=Tag.REVIEW)
        .annotate(comment_total=Count('comments'))
        .order_by('-created_at', '-id')[:limit]
    )
    return _feed_items(takes, viewer)


def my_takes(viewer):
    """The viewer's own reviews, newest first."""
    takes = list(
        Take.objects.select_related('author')
        .prefetch_related('votes')
        .filter(author=viewer, tag=Tag.REVIEW)
        .annotate(comment_total=Count('comments'))
        .order_by('-created_at', '-id')
    )
    return _feed_items(takes, viewer)
