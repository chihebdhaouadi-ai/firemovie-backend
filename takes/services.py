from django.db import IntegrityError, transaction
from django.db.models import Count
from rest_framework import serializers

from .errors import TakeError
from .models import FilmReaction, Reaction, Take, TakeComment, TakeVote, VoteKind

REACTION_KEYS = [choice.value for choice in Reaction]
VOTE_KINDS = [choice.value for choice in VoteKind]
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
        Take.objects.filter(film_id=film_id, author=user).update(reaction=reaction)


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
        'is_mine': take.author_id == viewer.id,
        'reaction': take.reaction,
        'body': take.body,
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


def create_take(film_id, user, body):
    reaction = (
        FilmReaction.objects.filter(film_id=film_id, user=user)
        .values_list('reaction', flat=True)
        .first()
    )
    if reaction is None:
        raise TakeError(400, 'reaction_required', 'Pick a reaction before sharing a take.')
    if Take.objects.filter(film_id=film_id, author=user).exists():
        raise TakeError(409, 'already_posted', 'You already shared a take for this film.')
    try:
        with transaction.atomic():
            take = Take.objects.create(film_id=film_id, author=user, reaction=reaction, body=body)
    except IntegrityError:
        raise TakeError(409, 'already_posted', 'You already shared a take for this film.')
    return _item(take, user)


def set_vote(take, user, kind, active):
    if active:
        TakeVote.objects.get_or_create(take=take, user=user, kind=kind)
    else:
        TakeVote.objects.filter(take=take, user=user, kind=kind).delete()


def comment_item(comment, take):
    return {
        'id': comment.id,
        'author_id': comment.author_id,
        'author_name': comment.author.username,
        'body': comment.body,
        'created_at': serializers.DateTimeField().to_representation(comment.created_at),
        'is_writer': comment.author_id == take.author_id,
    }


def comments_for_take(take):
    return [
        comment_item(comment, take)
        for comment in TakeComment.objects.filter(take=take).select_related('author').order_by('created_at', 'id')
    ]


def create_comment(take, user, body):
    comment = TakeComment.objects.create(take=take, author=user, body=body)
    return comment_item(comment, take)
