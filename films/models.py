from django.db import models
from django.conf import settings


class FilmEntry(models.Model):
    LIST_CHOICES = [
        ('top_5', 'Top 5'),
        ('watched', 'Watched'),
        ('watchlist', 'Watchlist'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='film_entries')
    imdb_id = models.CharField(max_length=20)
    list_type = models.CharField(max_length=20, choices=LIST_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'film_entries'
        unique_together = ('user', 'imdb_id', 'list_type')

    def __str__(self):
        return f'{self.user.email} - {self.imdb_id} [{self.list_type}]'