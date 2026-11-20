"""Lists of films people make, name and post: "Best heist films", "Cry
every time". Friends see them, give them a heart and comment on them."""

from django.conf import settings
from django.db import models

MAX_NAME_LENGTH = 80
MAX_FILMS = 50
MAX_COMMENT_LENGTH = 1000


class MovieList(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='movie_lists',
    )
    name = models.CharField(max_length=MAX_NAME_LENGTH)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at', '-id')

    def __str__(self):
        return f'{self.name} ({self.owner_id})'


class MovieListItem(models.Model):
    """One film in a list, with the title and poster it had when added, so a
    list shows without looking every film up again."""

    movie_list = models.ForeignKey(MovieList, on_delete=models.CASCADE, related_name='items')
    film_id = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    poster_url = models.CharField(max_length=500, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('position', 'id')
        unique_together = ('movie_list', 'film_id')


class MovieListLike(models.Model):
    movie_list = models.ForeignKey(MovieList, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('movie_list', 'user')


class MovieListComment(models.Model):
    movie_list = models.ForeignKey(MovieList, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    body = models.TextField(max_length=MAX_COMMENT_LENGTH, blank=True)
    # A reply points at the comment it answers; top-level comments have none.
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    # An optional photo; a comment needs a body, a photo or both.
    image = models.FileField(upload_to='list_comments/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('created_at',)


class SavedMovieList(models.Model):
    """Someone else's list you kept for later; it shows on your profile."""

    movie_list = models.ForeignKey(MovieList, on_delete=models.CASCADE, related_name='saves')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_movie_lists',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')
        unique_together = ('movie_list', 'user')
