from django.db import transaction
from django.db.models import Count

from accounts.models import User

from .errors import ListRuleError
from .models import TOP5_SIZE, FilmEntry

TOP_5 = FilmEntry.ListType.TOP_5
WATCHED = FilmEntry.ListType.WATCHED
WATCHLIST = FilmEntry.ListType.WATCHLIST


def _lock_user(user):
    User.objects.select_for_update().filter(pk=user.pk).first()


def entries_for(user, list_type):
    queryset = FilmEntry.objects.filter(user=user, list_type=list_type)
    if list_type == TOP_5:
        return queryset.order_by('slot_index')
    return queryset


def film_ids_for(user, list_type):
    return list(entries_for(user, list_type).values_list('film_id', flat=True))


def counts_for(user):
    rows = (
        FilmEntry.objects.filter(user=user)
        .values('list_type')
        .annotate(total=Count('id'))
    )
    totals = {list_type: 0 for list_type in FilmEntry.ListType.values}
    for row in rows:
        totals[row['list_type']] = row['total']
    return totals


def lists_containing(user, film_ids):
    memberships = {film_id: [] for film_id in film_ids}
    rows = FilmEntry.objects.filter(user=user, film_id__in=film_ids)
    for row in rows:
        memberships[row.film_id].append(row.list_type)
    return memberships


def add_top5(user, film_id, slot=None, replace=False):
    with transaction.atomic():
        _lock_user(user)
        existing = FilmEntry.objects.filter(
            user=user, list_type=TOP_5, film_id=film_id,
        ).first()
        if existing is not None:
            return existing, False

        occupied = {
            entry.slot_index: entry
            for entry in FilmEntry.objects.filter(user=user, list_type=TOP_5)
        }
        if slot is None:
            if len(occupied) >= TOP5_SIZE:
                raise ListRuleError(
                    409, 'top5_full',
                    'Your Top 5 is full. Remove a film first.',
                )
            slot = min(
                candidate for candidate in range(1, TOP5_SIZE + 1)
                if candidate not in occupied
            )
        elif slot in occupied:
            if not replace:
                raise ListRuleError(
                    409, 'top5_slot_taken',
                    f'Slot {slot} is already taken.',
                )
            occupied[slot].delete()

        entry = FilmEntry.objects.create(
            user=user, film_id=film_id, list_type=TOP_5, slot_index=slot,
        )
        return entry, True


def move_top5(user, film_id, slot):
    with transaction.atomic():
        _lock_user(user)
        entry = FilmEntry.objects.filter(
            user=user, list_type=TOP_5, film_id=film_id,
        ).first()
        if entry is None:
            raise ListRuleError(404, 'not_in_list', 'Film is not in your Top 5.')
        if entry.slot_index == slot:
            return entry

        previous_slot = entry.slot_index
        displaced_film_id = None
        occupant = FilmEntry.objects.filter(
            user=user, list_type=TOP_5, slot_index=slot,
        ).first()
        if occupant is not None:
            displaced_film_id = occupant.film_id
            occupant.delete()

        entry.slot_index = slot
        entry.save(update_fields=['slot_index'])
        if displaced_film_id is not None:
            FilmEntry.objects.create(
                user=user,
                film_id=displaced_film_id,
                list_type=TOP_5,
                slot_index=previous_slot,
            )
        return entry


def add_watched(user, film_id):
    with transaction.atomic():
        _lock_user(user)
        removed_from_watchlist = bool(
            FilmEntry.objects.filter(
                user=user, list_type=WATCHLIST, film_id=film_id,
            ).delete()[0]
        )
        entry, created = FilmEntry.objects.get_or_create(
            user=user, film_id=film_id, list_type=WATCHED,
        )
        return entry, created, removed_from_watchlist


def add_watchlist(user, film_id):
    with transaction.atomic():
        _lock_user(user)
        if FilmEntry.objects.filter(
            user=user, list_type=WATCHED, film_id=film_id,
        ).exists():
            raise ListRuleError(
                409, 'already_watched',
                'You already watched this film.',
            )
        return FilmEntry.objects.get_or_create(
            user=user, film_id=film_id, list_type=WATCHLIST,
        )


def remove_entry(user, list_type, film_id):
    deleted, _ = FilmEntry.objects.filter(
        user=user, list_type=list_type, film_id=film_id,
    ).delete()
    if not deleted:
        raise ListRuleError(404, 'not_in_list', 'Film is not in this list.')


def popular_watched(limit=20):
    return (
        FilmEntry.objects.filter(list_type=WATCHED)
        .values('film_id')
        .annotate(count=Count('id'))
        .order_by('-count', 'film_id')[:limit]
    )
