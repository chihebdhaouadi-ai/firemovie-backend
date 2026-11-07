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


class VoteKind(models.TextChoices):
    CHANGED_MY_MIND = 'changed_my_mind', 'Changed my mind'
    WELL_ARGUED = 'well_argued', 'Well argued'
    DISAGREE_BUT_FAIR = 'disagree_but_fair', 'Disagree but fair'
    # Questions and discussions only; reviews keep the three reaction kinds above.
    LIKE = 'like', 'Like'
    DISLIKE = 'dislike', 'Dislike'


TOPIC_VOTE_KINDS = (VoteKind.LIKE, VoteKind.DISLIKE)


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
        constraints = [
            UniqueConstraint(fields=['film_id', 'user'], name='film_reaction_unique_per_user'),
        ]


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
    body = models.TextField(max_length=280)
    image = models.FileField(upload_to='takes/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

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


class TakeComment(models.Model):
    take = models.ForeignKey(Take, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='take_comments',
    )
    body = models.CharField(max_length=300)
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'take_comments'
        ordering = ['created_at', 'id']
