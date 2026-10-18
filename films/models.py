from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint

TOP5_SIZE = 5


class FilmEntry(models.Model):
    class ListType(models.TextChoices):
        TOP_5 = 'top_5', 'Top 5'
        WATCHED = 'watched', 'Watched'
        WATCHLIST = 'watchlist', 'Watchlist'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='film_entries',
    )
    film_id = models.CharField(max_length=64)
    list_type = models.CharField(max_length=16, choices=ListType.choices)
    slot_index = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'film_entries'
        ordering = ['-created_at', '-id']
        constraints = [
            UniqueConstraint(
                fields=['user', 'film_id', 'list_type'],
                name='film_entry_unique_per_list',
            ),
            UniqueConstraint(
                fields=['user', 'slot_index'],
                condition=Q(list_type='top_5'),
                name='film_entry_unique_top5_slot',
            ),
            CheckConstraint(
                condition=~Q(list_type='top_5')
                | Q(slot_index__gte=1, slot_index__lte=TOP5_SIZE),
                name='film_entry_top5_slot_range',
            ),
        ]

    def __str__(self):
        return f'{self.user_id}:{self.list_type}:{self.film_id}'
