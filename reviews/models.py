from django.db import models
from django.conf import settings


class Review(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    imdb_id = models.CharField(max_length=20, db_index=True)
    rating = models.IntegerField()  # 1-5
    body = models.TextField(blank=True)
    writer_name = models.CharField(max_length=150)
    writer_image = models.URLField(blank=True, default='')
    likes = models.IntegerField(default=0)
    dislikes = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reviews'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.writer_name} - {self.imdb_id}'