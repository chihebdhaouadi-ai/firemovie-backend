import re
from collections import Counter
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import serializers

from films.catalog import try_stored_film
from accounts.models import User
from social.models import FriendRequest, Notification

from .errors import TakeError
from films.models import Film

from .models import (
    MAX_REACTIONS_PER_FILM,
    CardSkin,
    REVIEW_VOTE_KINDS,
    STANCE_VOTE,
    TOPIC_VOTE_KINDS,
    FilmReaction,
    PollOption,
    PollVote,
    Reaction,
    Tag,
    Take,
    TakeComment,
    TakeCommentVote,
    TakeReport,
    TakeVote,
    VoteKind,
)

REACTION_KEYS = [choice.value for choice in Reaction]
# What clients may vote with; the former review kinds are no longer accepted.
VOTE_KINDS = [kind.value for kind in (*REVIEW_VOTE_KINDS, *TOPIC_VOTE_KINDS)]
COMMENT_VOTE_KINDS = [VoteKind.LIKE, VoteKind.DISLIKE]
TAG_KEYS = [choice.value for choice in Tag]
EXPLORE_LIMIT = 30
TRENDING_LIMIT = 10
TOP_TAKES_LIMIT = 100
FRIEND_TAKES_LIMIT = 20
TRENDING_WINDOW = timedelta(days=7)
# How far back a friend's takes and comments count as stories.
STORY_WINDOW = timedelta(days=7)
STORY_ITEMS_PER_FRIEND = 10
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
        TakeVote.objects.filter(kind=VoteKind.UP, take__author_id__in=user_ids)
        .values('take__author_id')
        .annotate(total=Count('id'))
    )
    received = {row['take__author_id']: row['total'] for row in rows}
    return {
        user_id: 1 + TRUST_STEP * min(received.get(user_id, 0), MAX_WELL_ARGUED_BONUS)
        for user_id in user_ids
    }


def _leaning(feelings):
    """+1 when a person's feelings are mostly positive, -1 mostly negative, 0 mixed/neutral."""
    score = sum(1 for f in feelings if f in POSITIVE) - sum(1 for f in feelings if f in NEGATIVE)
    return (score > 0) - (score < 0)


def summary_payload(film_id, viewer):
    reactions = list(
        FilmReaction.objects.filter(film_id=film_id)
        .order_by('id')
        .values_list('user_id', 'reaction')
    )
    counts = {key: 0 for key in REACTION_KEYS}
    by_user = {}
    for user_id, reaction in reactions:
        counts[reaction] += 1
        by_user.setdefault(user_id, []).append(reaction)

    # Percentages count people, not feelings: each person leans one way or is left out.
    positive = [user_id for user_id, feelings in by_user.items() if _leaning(feelings) > 0]
    negative = [user_id for user_id, feelings in by_user.items() if _leaning(feelings) < 0]
    weights = _trust_weights(set(positive) | set(negative))
    weighted_positive = sum(weights[user_id] for user_id in positive)
    weighted_negative = sum(weights[user_id] for user_id in negative)

    most_felt = sorted(
        ((key, count) for key, count in counts.items() if count > 0),
        key=lambda item: (-item[1], REACTION_KEYS.index(item[0])),
    )[:3]
    my_reactions = by_user.get(viewer.id, [])

    return {
        'film_id': film_id,
        # People who reacted; counts are per feeling, so they can add up to more.
        'total': len(by_user),
        'counts': counts,
        'my_reactions': my_reactions,
        # Kept for older clients: the first feeling picked.
        'my_reaction': my_reactions[0] if my_reactions else None,
        'most_felt': [{'reaction': key, 'count': count} for key, count in most_felt],
        'everyone_percent': _percent(len(positive), len(positive) + len(negative)),
        'trusted_percent': _percent(weighted_positive, weighted_positive + weighted_negative),
    }


def set_reactions(film_id, user, reactions):
    """Replace the person's feelings for a film (up to MAX_REACTIONS_PER_FILM, in pick order).
    An empty list clears them. Their review keeps the first feeling as its reaction."""
    reactions = list(dict.fromkeys(reactions))[:MAX_REACTIONS_PER_FILM]
    with transaction.atomic():
        FilmReaction.objects.filter(film_id=film_id, user=user).delete()
        FilmReaction.objects.bulk_create(
            FilmReaction(film_id=film_id, user=user, reaction=reaction) for reaction in reactions
        )
        if reactions:
            Take.objects.filter(film_id=film_id, author=user, tag=Tag.REVIEW).update(
                reaction=reactions[0],
            )


def set_reaction(film_id, user, reaction):
    set_reactions(film_id, user, [] if reaction is None else [reaction])


def _author_reactions(film_id, author_ids):
    """Each author's current feelings for a film, in pick order, in one query."""
    feelings = {}
    rows = (
        FilmReaction.objects.filter(film_id=film_id, user_id__in=set(author_ids))
        .order_by('id')
        .values_list('user_id', 'reaction')
    )
    for user_id, reaction in rows:
        feelings.setdefault(user_id, []).append(reaction)
    return feelings


def _item(take, viewer, is_most_helpful=False, author_reactions=None):
    counts = {kind: 0 for kind in VOTE_KINDS}
    my_votes = []
    for vote in take.votes.all():
        counts[vote.kind] += 1
        if vote.user_id == viewer.id:
            my_votes.append(vote.kind)
    comment_count = getattr(take, 'comment_total', None)
    if comment_count is None:
        comment_count = take.comments.count()
    poll_options, my_poll_option_id = _poll_fields(take, viewer)
    return {
        'id': take.id,
        'film_id': take.film_id,
        'author_id': take.author_id,
        'author_name': take.author.username,
        'author_avatar': take.author.avatar.url if take.author.avatar else None,
        'author_frame': take.author.equipped_frame,
        'is_mine': take.author_id == viewer.id,
        'reaction': take.reaction,
        # The author's current feelings (up to three); falls back to the one
        # stored on the take when the caller did not look them up.
        'author_reactions': (
            author_reactions
            if author_reactions is not None
            else ([take.reaction] if take.reaction else [])
        ),
        'tag': take.tag,
        'body': take.body,
        'image_url': take.image.url if take.image else None,
        'created_at': serializers.DateTimeField().to_representation(take.created_at),
        'votes': counts,
        'my_votes': my_votes,
        'comment_count': comment_count,
        'is_most_helpful': is_most_helpful,
        'spoiler': take.spoiler,
        'skin': take.skin,
        'edited': take.edited_at is not None,
        'scene': take.scene,
        'timecode': take.timecode,
        'poll_options': poll_options,
        'my_poll_option_id': my_poll_option_id,
    }


def _poll_fields(take, viewer):
    """Options with their vote counts, and the option the viewer picked (polls only)."""
    if take.tag != Tag.POLL:
        return [], None
    votes = list(take.poll_votes.all())
    counts = Counter(vote.option_id for vote in votes)
    mine = next((vote.option_id for vote in votes if vote.user_id == viewer.id), None)
    options = [
        {'id': option.id, 'label': option.label, 'votes': counts.get(option.id, 0)}
        for option in take.poll_options.all()
    ]
    return options, mine


def takes_for_film(film_id, viewer):
    takes = list(
        Take.objects.filter(film_id=film_id)
        .select_related('author')
        .prefetch_related('votes')
        .annotate(comment_total=Count('comments'))
    )

    def helpfulness(take):
        return sum(1 for vote in take.votes.all() if vote.kind == VoteKind.UP)

    ranked = sorted(takes, key=lambda take: (helpfulness(take), take.created_at, take.id), reverse=True)
    feelings = _author_reactions(film_id, [take.author_id for take in takes])
    items = []
    for index, take in enumerate(ranked):
        is_most_helpful = (
            index == 0 and helpfulness(take) > 0 and take.author_id != viewer.id
        )
        items.append(
            _item(
                take,
                viewer,
                is_most_helpful=is_most_helpful,
                author_reactions=feelings.get(take.author_id, []),
            )
        )
    return items


def take_item(take, viewer):
    return next(item for item in takes_for_film(take.film_id, viewer) if item['id'] == take.id)


def create_take(film_id, user, body, tag=Tag.REVIEW, skin=CardSkin.NORMAL, spoiler=False):
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
                film_id=film_id, author=user, reaction=reaction, tag=tag, body=body,
                skin=skin, spoiler=spoiler,
            )
    except IntegrityError:
        raise TakeError(409, 'already_posted', 'You already shared a take for this film.')
    try_stored_film(film_id)
    return _item(
        take, user, author_reactions=_author_reactions(film_id, [user.id]).get(user.id, [])
    )


def set_vote(take, user, kind, active):
    """Vote on a take: one of like/dislike on topics, one of up/draw/down on reviews."""
    with transaction.atomic():
        if active:
            for group in (TOPIC_VOTE_KINDS, REVIEW_VOTE_KINDS):
                if kind in group:
                    TakeVote.objects.filter(take=take, user=user, kind__in=group).exclude(kind=kind).delete()
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
        'stance': comment.stance,
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


# `@name` at the start or after a space/punctuation (not inside an email).
MENTION_PATTERN = re.compile(r'(?<![\w@])@([\w.+-]{1,150})')
MAX_MENTIONS_PER_COMMENT = 10


def mentioned_friends(user, body):
    """Friends of [user] tagged with `@username` in [body], at most ten."""
    names = []
    for match in MENTION_PATTERN.finditer(body):
        # A trailing dot or dash is punctuation, not part of the name.
        name = match.group(1).rstrip('.-+').lower()
        if name and name not in names:
            names.append(name)
    if not names:
        return []
    ids = friend_ids(user)
    if not ids:
        return []
    friends = User.objects.filter(id__in=ids)
    found = [friend for friend in friends if friend.username.lower() in names]
    return found[:MAX_MENTIONS_PER_COMMENT]


def create_comment(take, user, body, parent=None, stance=None):
    with transaction.atomic():
        comment = TakeComment.objects.create(
            take=take,
            author=user,
            body=body,
            parent=parent,
            stance=stance,
        )
        if stance is not None and parent is None and take.tag == Tag.REVIEW:
            set_vote(take, user, STANCE_VOTE[stance], True)
        # Tagged friends get a notification that opens this conversation.
        Notification.objects.bulk_create([
            Notification(
                recipient=friend,
                actor=user,
                kind=Notification.Kind.TAKE_MENTION,
                take=take,
                comment=comment,
            )
            for friend in mentioned_friends(user, body)
        ])
    return comment_item(comment, take, user)


def take_detail(take, viewer):
    """One take shaped like a feed item (with its film), for opening it alone."""
    return _feed_items([_reload_take(take.id)], viewer)[0]


def edit_take(take, body, skin=None, spoiler=None):
    """The author rewrites the body (and may change the card skin or spoiler flag)."""
    take.body = body
    fields = ['body', 'edited_at']
    if skin is not None:
        take.skin = skin
        fields.append('skin')
    if spoiler is not None:
        take.spoiler = spoiler
        fields.append('spoiler')
    take.edited_at = timezone.now()
    take.save(update_fields=fields)


def report_take(take, reporter, reason, details=''):
    """Records a report; a second report by the same viewer updates the first."""
    _, created = TakeReport.objects.update_or_create(
        take=take,
        reporter=reporter,
        defaults={'reason': reason, 'details': details},
    )
    return created


MAX_SHARE_RECIPIENTS = 20


def share_take(take, sender, recipient_ids, message=''):
    """Sends [take] to friends as a notification that opens it."""
    recipients = set(recipient_ids)
    if not recipients.issubset(friend_ids(sender)):
        raise TakeError(400, 'not_friends', 'You can only share takes with your friends.')
    Notification.objects.bulk_create([
        Notification(
            recipient_id=recipient_id,
            actor=sender,
            kind=Notification.Kind.TAKE_SHARED,
            take=take,
            message=message,
        )
        for recipient_id in sorted(recipients)
    ])
    return len(recipients)


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


def create_topic(user, body, tag, film_id='', image=None, options=None, scene='', timecode='', spoiler=False,
                 skin=CardSkin.NORMAL):
    """A question, discussion, hot take, poll or scene, optionally about a film and/or with a photo."""
    try:
        with transaction.atomic():
            take = Take.objects.create(
                film_id=film_id or '', author=user, reaction=None, tag=tag,
                body=body, image=image or None, spoiler=spoiler,
                scene=scene or '', timecode=timecode or '', skin=skin,
            )
            for position, label in enumerate(options or []):
                PollOption.objects.create(take=take, label=label, position=position)
    except IntegrityError:
        raise TakeError(409, 'already_posted', 'Could not save your topic.')
    if film_id:
        try_stored_film(film_id)
    return _item(take, user)


def vote_poll(take, user, option_id):
    """Pick one option on a poll, replacing the viewer's earlier pick."""
    if take.tag != Tag.POLL:
        raise TakeError(400, 'not_a_poll', 'Only polls take a choice.')
    option = take.poll_options.filter(id=option_id).first()
    if option is None:
        raise TakeError(400, 'invalid_option', 'Pick one of the options on this poll.')
    PollVote.objects.update_or_create(take=take, user=user, defaults={'option': option})
    return _item(_reload_take(take.id), user)


def _reload_take(take_id):
    return (
        Take.objects.select_related('author')
        .prefetch_related('votes', 'poll_options', 'poll_votes')
        .annotate(comment_total=Count('comments'))
        .get(id=take_id)
    )


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
        .prefetch_related('votes', 'poll_options', 'poll_votes')
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


def top_takes(viewer, tag=None, limit=TOP_TAKES_LIMIT):
    """All-time most engaging takes, optionally of one tag. Replies count double."""
    takes = Take.objects.select_related('author').prefetch_related(
        'votes', 'poll_options', 'poll_votes',
    )
    if tag:
        takes = takes.filter(tag=tag)
    takes = list(
        takes.annotate(
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


def friend_stories(viewer, now=None):
    """Each friend's recent creations (takes of any kind and comments), as
    story groups: one per friend, newest friend first, items oldest first so
    they play in the order they were made."""
    ids = friend_ids(viewer)
    if not ids:
        return []
    since = (now or timezone.now()) - STORY_WINDOW
    takes = list(
        Take.objects.select_related('author')
        .filter(author_id__in=ids, created_at__gte=since)
        .order_by('-created_at', '-id')
    )
    comments = list(
        TakeComment.objects.select_related('author', 'take')
        .filter(author_id__in=ids, created_at__gte=since)
        .order_by('-created_at', '-id')
    )
    film_ids = {take.film_id for take in takes} | {c.take.film_id for c in comments}
    films = {film.imdb_id: film for film in Film.objects.filter(imdb_id__in=film_ids)}

    def film_of(film_id):
        film = films.get(film_id)
        return {
            'film_id': film_id,
            'title': (film.title or None) if film else None,
            'poster_url': film.poster_url if film else None,
        }

    groups = {}
    for take in takes:
        groups.setdefault(take.author_id, {'user': take.author, 'items': []})['items'].append({
            'kind': 'take',
            'id': take.id,
            'take_id': take.id,
            'tag': take.tag,
            'body': take.body,
            'spoiler': take.spoiler,
            'film': film_of(take.film_id),
            'created_at': take.created_at,
        })
    for comment in comments:
        groups.setdefault(comment.author_id, {'user': comment.author, 'items': []})['items'].append({
            'kind': 'comment',
            'id': comment.id,
            'take_id': comment.take_id,
            'tag': comment.take.tag,
            'body': comment.body,
            'spoiler': comment.take.spoiler,
            'film': film_of(comment.take.film_id),
            'created_at': comment.created_at,
        })
    result = []
    for group in groups.values():
        items = sorted(group['items'], key=lambda item: item['created_at'], reverse=True)
        items = items[:STORY_ITEMS_PER_FRIEND]
        items.reverse()
        result.append({
            'user': group['user'],
            'latest_at': items[-1]['created_at'],
            'items': items,
        })
    result.sort(key=lambda group: group['latest_at'], reverse=True)
    return result


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
