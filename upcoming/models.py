from django.core.validators import FileExtensionValidator
from django.db import models


class UpcomingFilm(models.Model):
    """A film that is not out yet, added by staff in the Django admin.

    The app shows the poster on the home page. Tapping it tells the user the
    film is not out yet and when it releases.
    """

    title = models.CharField(max_length=200)
    poster = models.FileField(
        upload_to='upcoming/posters/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'webp'])],
        help_text='Poster shown on the home page.',
    )
    release_date = models.DateField()
    description = models.TextField(blank=True)
    published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['release_date', 'id']

    def __str__(self):
        return f'{self.title} ({self.release_date})'
