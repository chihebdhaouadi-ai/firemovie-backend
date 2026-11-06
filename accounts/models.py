from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    balance = models.IntegerField(default=5)
    bio = models.CharField(max_length=280, blank=True, default='')
    avatar = models.FileField(upload_to='avatars/', blank=True, null=True)
    cover = models.FileField(upload_to='covers/', blank=True, null=True)
    equipped_frame = models.CharField(max_length=20, default='bronze')

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email or self.username