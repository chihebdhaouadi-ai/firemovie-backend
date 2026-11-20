from django.conf import settings
from django.db import models
from django.db.models import Q, UniqueConstraint


class Reaction(models.TextChoices):
    LOVED = 'loved', 'Loved it'
    BROKE_HEART = 'broke_heart', 'Broke my heart'
    BLEW_MIND = 'blew_mind', 'Blew my mind'
    MADE_CRY = 'made_cry', 'Made me cry'
    SHOCKED = 'shocked', 'Shocked me'
    MADE_LAUGH = 'made_laugh', 'Made me laugh'
    BORED = 'bored', 'Bored me'
    DISAPPOINTED = 'disappointed', 'Disappointed me'
    MADE_THINK = 'made_think', 'Made me think'
    MASTERPIECE = 'masterpiece', 'Masterpiece'


class Tag(models.TextChoices):
    REVIEW = 'review', 'Review'
    QUESTION = 'question', 'Question'
    DISCUSSION = 'discussion', 'Discussion'
    HOT_TAKE = 'hot_take', 'Hot take'
    POLL = 'poll', 'Poll'
    SCENE = 'scene', 'Scene'


class CardSkin(models.TextChoices):
    """The background a take card is drawn with. Every user owns these two."""

    NORMAL = 'normal', 'Normal'
    ELECTRIC_THUNDER = 'electric_thunder', 'Electric thunder'


class ReportReason(models.TextChoices):
    SPAM = 'spam', 'Spam'
    HARASSMENT = 'harassment', 'Harassment or bullying'
    HATE = 'hate', 'Hate speech'
    SPOILER = 'spoiler', 'Unmarked spoiler'
    OTHER = 'other', 'Something else'


class VoteKind(models.TextChoices):
    # Reviews: one of up, draw or down per reader.
    UP = 'up', 'Up'
    DRAW = 'draw', 'Draw'
    DOWN = 'down', 'Down'
    # Questions and discussions only.
    LIKE = 'like', 'Like'
    DISLIKE = 'dislike', 'Dislike'
    # Former review votes, migrated to up/draw. Kept as comment stance values.
    CHANGED_MY_MIND = 'changed_my_mind', 'Changed my mind'
    WELL_ARGUED = 'well_argued', 'Well argued'
    DISAGREE_BUT_FAIR = 'disagree_but_fair', 'Disagree but fair'


class CommentStance(models.TextChoices):
    CHANGED_MY_MIND = VoteKind.CHANGED_MY_MIND, 'Changed my mind'
    DISAGREE_BUT_FAIR = VoteKind.DISAGREE_BUT_FAIR, 'Disagree but fair'


TOPIC_VOTE_KINDS = (VoteKind.LIKE, VoteKind.DISLIKE)
REVIEW_VOTE_KINDS = (VoteKind.UP, VoteKind.DRAW, VoteKind.DOWN)

# The review vote a top-level comment stance also casts.
STANCE_VOTE = {
    'changed_my_mind': VoteKind.UP,
    'disagree_but_fair': VoteKind.DRAW,
}


MAX_REACTIONS_PER_FILM = 3


class FilmReaction(models.Model):
    film_id = models.CharField(max_length=20, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='film_reactions',
    )
    reaction = models.CharField(max_length=16, choices=Reaction.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'take_film_reactions'
        # A person can pick up to MAX_REACTIONS_PER_FILM feelings for a film, each once.
        constraints = [
            UniqueConstraint(
                fields=['film_id', 'user', 'reaction'],
                name='film_reaction_unique_per_user_feeling',
            ),
        ]
        ordering = ['id']


class Take(models.Model):
    # Blank for photo topics that are not about a specific film.
    film_id = models.CharField(max_length=20, db_index=True, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='takes',
    )
    reaction = models.CharField(max_length=16, choices=Reaction.choices, null=True, blank=True)
    tag = models.CharField(max_length=16, choices=Tag.choices, default=Tag.REVIEW)
    # Topics only, optional: a short headline shown above the body.
    title = models.CharField(max_length=120, blank=True, default='')
    body = models.TextField(max_length=1500)
    image = models.FileField(upload_to='takes/', blank=True, null=True)
    # Topics only: the body may give away the plot, so the app blurs it until tapped.
    spoiler = models.BooleanField(default=False)
    # Scene topics only: the moment being discussed and where it happens.
    scene = models.CharField(max_length=120, blank=True, default='')
    timecode = models.CharField(max_length=20, blank=True, default='')
    # The card background others see this take drawn with.
    skin = models.CharField(max_length=24, choices=CardSkin.choices, default=CardSkin.NORMAL)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the author changes the body after posting.
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'takes'
        constraints = [
            # Only reviews are limited to one per author per film; questions and
            # discussions can be posted freely.
            UniqueConstraint(
                fields=['film_id', 'author'],
                condition=Q(tag='review'),
                name='take_unique_per_author',
            ),
        ]


class SavedTake(models.Model):
    """A take someone saved to come back to; shown on their profile."""

    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='saves')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_takes',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_saves'
        ordering = ('-created_at', '-id')
        constraints = [
            UniqueConstraint(fields=['take', 'user'], name='take_save_unique'),
        ]


class TakeVote(models.Model):
    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='take_votes',
    )
    kind = models.CharField(max_length=24, choices=VoteKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_votes'
        constraints = [
            UniqueConstraint(fields=['take', 'user', 'kind'], name='take_vote_unique'),
        ]


class PollOption(models.Model):
    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='poll_options')
    label = models.CharField(max_length=80)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'take_poll_options'
        ordering = ['position', 'id']


class PollVote(models.Model):
    """A viewer's single choice on a poll. Changing it replaces the old choice."""

    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='poll_votes')
    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='poll_votes',
    )
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'take_poll_votes'
        constraints = [
            UniqueConstraint(fields=['take', 'user'], name='poll_vote_unique_per_user'),
        ]


class TakeCommentVote(models.Model):
    """A like or dislike on a comment. A viewer holds at most one per comment."""

    comment = models.ForeignKey('TakeComment', on_delete=models.CASCADE, related_name='votes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='take_comment_votes',
    )
    kind = models.CharField(max_length=8, choices=[(VoteKind.LIKE, 'Like'), (VoteKind.DISLIKE, 'Dislike')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_comment_votes'
        constraints = [
            UniqueConstraint(fields=['comment', 'user'], name='take_comment_vote_unique'),
        ]


class TakeComment(models.Model):
    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='take_comments',
    )
    body = models.CharField(max_length=300)
    stance = models.CharField(
        max_length=24,
        choices=CommentStance.choices,
        null=True,
        blank=True,
        default=None,
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    # An optional photo; a comment needs a body, a photo or both.
    image = models.FileField(upload_to='comments/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_comments'
        ordering = ['created_at', 'id']


class TakeReport(models.Model):
    """A viewer flagging a take for moderators. One report per viewer per take."""

    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='take_reports',
    )
    reason = models.CharField(max_length=16, choices=ReportReason.choices)
    details = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_reports'
        ordering = ['-created_at', '-id']
        constraints = [
            UniqueConstraint(fields=['take', 'reporter'], name='take_report_unique_per_user'),
        ]
