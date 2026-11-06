"""Reviewer leaderboard and profile progression.

A reaction is a TakeVote on a review take. Each (take, voter) pair counts once,
at the earliest vote that voter cast on that take, and self-votes never count.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Min, OuterRef, Subquery
from django.utils import timezone

from .errors import TakeError
from .models import Tag, Take, TakeComment, TakeVote, VoteKind

PERIODS = ('week', 'month', 'all')
LEADERBOARD_SIZE = 20
TOP_CRITIC_RANK = 3
FRAME_KEYS = ('bronze', 'explorer', 'debater', 'gold', 'legend')

XP_PER_REVIEW = 20
XP_PER_COMMENT = 5
XP_PER_REACTION = 2


def total_xp(level):
    """Cumulative XP needed to reach `level`. Level 1 starts at 0 XP."""
    return 100 * (level - 1) + 25 * (level - 1) * (level - 2)


def level_for_xp(xp):
    level = 1
    while total_xp(level + 1) <= xp:
        level += 1
    return level


def period_start(period, now=None):
    """Lower bound for a leaderboard period, or None for all time."""
    if period not in PERIODS:
        raise TakeError(400, 'invalid_period', 'Pick week, month or all.')
    if period == 'all':
        return None
    local_now = timezone.localtime(now or timezone.now())
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        return midnight - timedelta(days=local_now.weekday())
    return midnight.replace(day=1)


def _reaction_rows(author_id=None, since=None):
    """One row per counted (take, voter) pair, with the time it happened."""
    votes = TakeVote.objects.filter(take__tag=Tag.REVIEW).exclude(user_id=F('take__author_id'))
    if author_id is not None:
        votes = votes.filter(take__author_id=author_id)
    pairs = votes.values('take__author_id', 'take_id', 'user_id').annotate(reacted_at=Min('created_at'))
    if since is not None:
        pairs = pairs.filter(reacted_at__gte=since)
    return list(pairs)


def _ranking(since):
    """Authors with at least one counted reaction since `since`, best first."""
    totals = {}
    for row in _reaction_rows(since=since):
        author_id = row['take__author_id']
        reactions, reached_at = totals.get(author_id, (0, row['reacted_at']))
        totals[author_id] = (reactions + 1, max(reached_at, row['reacted_at']))
    ranked = [
        {'user_id': author_id, 'reactions': reactions, 'reached_at': reached_at}
        for author_id, (reactions, reached_at) in totals.items()
    ]
    ranked.sort(key=lambda row: (-row['reactions'], row['reached_at'], row['user_id']))
    return ranked


def _review_counts(since=None, author_ids=None):
    reviews = Take.objects.filter(tag=Tag.REVIEW)
    if since is not None:
        reviews = reviews.filter(created_at__gte=since)
    if author_ids is not None:
        reviews = reviews.filter(author_id__in=author_ids)
    rows = reviews.values('author_id').annotate(total=Count('id'))
    return {row['author_id']: row['total'] for row in rows}


def _avatar_url(user, request):
    return request.build_absolute_uri(user.avatar.url) if user.avatar else None


def _leaderboard_entry(user, request, reviews, reactions):
    return {
        'user_id': user.id,
        'username': user.username,
        'avatar': _avatar_url(user, request),
        'equipped_frame': user.equipped_frame,
        'reviews': reviews,
        'reactions': reactions,
    }


def leaderboard_payload(viewer, period, request):
    since = period_start(period)
    ranked = _ranking(since)
    my_index = next((i for i, row in enumerate(ranked) if row['user_id'] == viewer.id), None)
    top = ranked[:LEADERBOARD_SIZE]
    wanted = {row['user_id'] for row in top} | {viewer.id}
    users = get_user_model().objects.in_bulk(wanted)
    reviews = _review_counts(since, wanted)

    entries = [
        {
            'rank': rank,
            **_leaderboard_entry(
                users[row['user_id']], request,
                reviews.get(row['user_id'], 0), row['reactions'],
            ),
        }
        for rank, row in enumerate(top, start=1)
    ]
    my_row = ranked[my_index] if my_index is not None else None
    me = {
        'rank': my_index + 1 if my_index is not None else None,
        **_leaderboard_entry(
            viewer, request,
            reviews.get(viewer.id, 0), my_row['reactions'] if my_row else 0,
        ),
    }
    return {'period': period, 'entries': entries, 'me': me}


def _first_review_on_film():
    return (
        Take.objects.filter(tag=Tag.REVIEW, film_id=OuterRef('film_id'))
        .order_by('created_at', 'id')
        .values('id')[:1]
    )


def _achievement(key, current, target, available=True):
    return {
        'key': key,
        'current': current,
        'target': target,
        'unlocked': available and current >= target,
        'available': available,
    }


def _badge(key, current, target):
    return {'key': key, 'current': current, 'target': target, 'unlocked': current >= target}


def _frame(key, current, target):
    return {'key': key, 'current': current, 'target': target, 'unlocked': current >= target}


def progress_for(user):
    reviews = Take.objects.filter(author=user, tag=Tag.REVIEW).count()
    comments = TakeComment.objects.filter(author=user).count()
    reactions = len(_reaction_rows(author_id=user.id))
    kind_rows = (
        TakeVote.objects.filter(take__author=user, take__tag=Tag.REVIEW)
        .exclude(user=user)
        .values('kind')
        .annotate(total=Count('id'))
    )
    kinds = {row['kind']: row['total'] for row in kind_rows}
    well_argued = kinds.get(VoteKind.WELL_ARGUED, 0)
    changed_my_mind = kinds.get(VoteKind.CHANGED_MY_MIND, 0)
    disagree_but_fair = kinds.get(VoteKind.DISAGREE_BUT_FAIR, 0)
    first_takes = (
        Take.objects.filter(author=user, tag=Tag.REVIEW)
        .exclude(film_id='')
        .annotate(first_id=Subquery(_first_review_on_film()))
        .filter(first_id=F('id'))
        .count()
    )
    week = _ranking(period_start('week'))
    top_critic = any(row['user_id'] == user.id for row in week[:TOP_CRITIC_RANK])

    xp = XP_PER_REVIEW * reviews + XP_PER_COMMENT * comments + XP_PER_REACTION * reactions
    level = level_for_xp(xp)
    level_floor = total_xp(level)
    return {
        'level': level,
        'xp': xp,
        'xp_into_level': xp - level_floor,
        'xp_for_next_level': total_xp(level + 1) - level_floor,
        'reviews': reviews,
        'reactions': reactions,
        'comments': comments,
        'achievements': [
            _achievement('film_critic', reviews, 10),
            _achievement('debater', well_argued, 50),
            _achievement('local_cinema', 0, 20, available=False),
        ],
        'badges': [
            _badge('well_argued', well_argued, 10),
            _badge('changed_my_mind', changed_my_mind, 10),
            _badge('disagree_but_fair', disagree_but_fair, 10),
            _badge('top_critic', 1 if top_critic else 0, 1),
            _badge('first_take', first_takes, 1),
        ],
        'frames': [
            _frame('bronze', 0, 0),
            _frame('explorer', level, 10),
            _frame('debater', well_argued, 50),
            _frame('gold', level, 15),
            _frame('legend', level, 30),
        ],
    }


def is_frame_unlocked(user, key):
    return any(frame['key'] == key and frame['unlocked'] for frame in progress_for(user)['frames'])
