import django.db.models
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('films', '0002_film_entry_lists'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='top_movies',
        ),
        migrations.RemoveField(
            model_name='user',
            name='watched_movies',
        ),
        migrations.RemoveField(
            model_name='user',
            name='watchlist_movies',
        ),
    ]
