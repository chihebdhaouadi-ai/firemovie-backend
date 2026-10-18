from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    balance = models.IntegerField(default=5)
    top_movies = models.JSONField(default=list, blank=True)
    watched_movies = models.JSONField(default=list, blank=True)
    watchlist_movies = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email or self.username