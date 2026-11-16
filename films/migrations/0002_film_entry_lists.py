from django.conf import settings
from django.db import migrations, models

TOP5_SIZE = 5
MAX_FILM_ID_LENGTH = 64


def _clean(values):
    cleaned = []
    for value in values or []:
        film_id = str(value).strip()[:MAX_FILM_ID_LENGTH]
        if film_id and film_id not in cleaned:
            cleaned.append(film_id)
    return cleaned


def copy_legacy_lists(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    FilmEntry = apps.get_model('films', 'FilmEntry')
    rows = []
    for user in User.objects.all().iterator():
        top = _clean(user.top_movies)[:TOP5_SIZE]
        watched = _clean(user.watched_movies)
        watched_set = set(watched)
        watchlist = [
            film_id for film_id in _clean(user.watchlist_movies)
            if film_id not in watched_set
        ]
        rows.extend(
            FilmEntry(user_id=user.pk, film_id=film_id, list_type='top_5', slot_index=slot)
            for slot, film_id in enumerate(top, start=1)
        )
        rows.extend(
            FilmEntry(user_id=user.pk, film_id=film_id, list_type='watched')
            for film_id in watched
        )
        rows.extend(
            FilmEntry(user_id=user.pk, film_id=film_id, list_type='watchlist')
            for film_id in watchlist
        )
    FilmEntry.objects.bulk_create(rows, batch_size=500)


def restore_legacy_lists(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    FilmEntry = apps.get_model('films', 'FilmEntry')
    for user in User.objects.all().iterator():
        entries = FilmEntry.objects.filter(user_id=user.pk)
        user.top_movies = list(
            entries.filter(list_type='top_5')
            .order_by('slot_index')
            .values_list('film_id', flat=True)
        )
        user.watched_movies = list(
            entries.filter(list_type='watched')
            .order_by('id')
            .values_list('film_id', flat=True)
        )
        user.watchlist_movies = list(
            entries.filter(list_type='watchlist')
            .order_by('id')
            .values_list('film_id', flat=True)
        )
        user.save(update_fields=['top_movies', 'watched_movies', 'watchlist_movies'])
    FilmEntry.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0001_initial'),
        ('films', '0001_initial'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='filmentry',
            unique_together=set(),
        ),
        migrations.RenameField(
            model_name='filmentry',
            old_name='imdb_id',
            new_name='film_id',
        ),
        migrations.AlterField(
            model_name='filmentry',
            name='film_id',
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name='filmentry',
            name='list_type',
            field=models.CharField(choices=[('top_5', 'Top 5'), ('watched', 'Watched'), ('watchlist', 'Watchlist')], max_length=16),
        ),
        migrations.AddField(
            model_name='filmentry',
            name='slot_index',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AlterModelOptions(
            name='filmentry',
            options={'ordering': ['-created_at', '-id']},
        ),
        migrations.AddConstraint(
            model_name='filmentry',
            constraint=models.UniqueConstraint(
                fields=('user', 'film_id', 'list_type'),
                name='film_entry_unique_per_list',
            ),
        ),
        migrations.AddConstraint(
            model_name='filmentry',
            constraint=models.UniqueConstraint(
                condition=models.Q(('list_type', 'top_5')),
                fields=('user', 'slot_index'),
                name='film_entry_unique_top5_slot',
            ),
        ),
        migrations.AddConstraint(
            model_name='filmentry',
            constraint=models.CheckConstraint(
                condition=~models.Q(('list_type', 'top_5'))
                | models.Q(('slot_index__gte', 1), ('slot_index__lte', 5)),
                name='film_entry_top5_slot_range',
            ),
        ),
        migrations.RunPython(copy_legacy_lists, restore_legacy_lists),
    ]
