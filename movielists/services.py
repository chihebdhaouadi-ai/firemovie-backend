from django.db import transaction
from django.db.models import Count, Exists, OuterRef

from social.serializers import UserCardSerializer
from takes.errors import TakeError
from takes.services import friend_ids

from .models import MovieList, MovieListComment, MovieListItem, MovieListLike, SavedMovieList

FRIENDS_LIMIT = 30
COVER_POSTERS = 4


def _annotated(queryset, viewer):
    return (
        queryset.select_related('owner')
        .prefetch_related('items')
        .annotate(
            like_count=Count('likes', distinct=True),
            comment_count=Count('comments', distinct=True),
            liked=Exists(MovieListLike.objects.filter(movie_list=OuterRef('pk'), user=viewer)),
            saved=Exists(SavedMovieList.objects.filter(movie_list=OuterRef('pk'), user=viewer)),
        )
        # Grouped queries drop the model's default ordering, so say it again.
        .order_by('-created_at', '-id')
    )


def _user(user, request=None):
    return UserCardSerializer(user, context={'request': request}).data


def list_item(movie_list, viewer, request=None):
    """A list as a card: its name, owner, how many films, the first few
    posters for the stacked cover, hearts and comments."""
    items = list(movie_list.items.all())
    return {
        'id': movie_list.id,
        'name': movie_list.name,
        'owner': _user(movie_list.owner, request),
        'is_mine': movie_list.owner_id == viewer.id,
        'film_count': len(items),
        'posters': [item.poster_url for item in items if item.poster_url][:COVER_POSTERS],
        'likes': getattr(movie_list, 'like_count', 0),
        'liked': bool(getattr(movie_list, 'liked', False)),
        'comments': getattr(movie_list, 'comment_count', 0),
        'saved': bool(getattr(movie_list, 'saved', False)),
        'created_at': movie_list.created_at,
    }


def list_detail(movie_list, viewer, request=None):
    data = list_item(movie_list, viewer, request)
    data['films'] = [
        {'film_id': item.film_id, 'title': item.title, 'poster_url': item.poster_url or None}
        for item in movie_list.items.all()
    ]
    return data


def my_lists(viewer):
    return _annotated(MovieList.objects.filter(owner=viewer), viewer)


def friends_lists(viewer):
    return _annotated(MovieList.objects.filter(owner_id__in=friend_ids(viewer)), viewer)[:FRIENDS_LIMIT]


def saved_lists(viewer, limit=100):
    """Lists you saved, the one you saved last first."""
    ids = list(
        SavedMovieList.objects.filter(user=viewer).values_list('movie_list_id', flat=True)[:limit]
    )
    by_id = {item.id: item for item in _annotated(MovieList.objects.filter(pk__in=ids), viewer)}
    return [by_id[i] for i in ids if i in by_id]


def set_saved(movie_list, user, active):
    if active:
        SavedMovieList.objects.get_or_create(movie_list=movie_list, user=user)
    else:
        SavedMovieList.objects.filter(movie_list=movie_list, user=user).delete()


def get_list(list_id, viewer):
    return _annotated(MovieList.objects.filter(pk=list_id), viewer).first()


def _set_films(movie_list, films):
    movie_list.items.all().delete()
    MovieListItem.objects.bulk_create([
        MovieListItem(
            movie_list=movie_list,
            film_id=film['film_id'],
            title=film['title'],
            poster_url=film.get('poster_url') or '',
            position=index,
        )
        for index, film in enumerate(films)
    ])


@transaction.atomic
def create_list(owner, name, films):
    movie_list = MovieList.objects.create(owner=owner, name=name)
    _set_films(movie_list, films)
    return movie_list


@transaction.atomic
def update_list(movie_list, name=None, films=None):
    if name is not None:
        movie_list.name = name
    movie_list.save()
    if films is not None:
        _set_films(movie_list, films)
    return movie_list


def set_like(movie_list, user, active):
    if active:
        MovieListLike.objects.get_or_create(movie_list=movie_list, user=user)
    else:
        MovieListLike.objects.filter(movie_list=movie_list, user=user).delete()


def share_list(movie_list, sender, recipient_ids, message='', request=None):
    """Sends a list into your chat with each friend picked, as a card that
    opens it."""
    from messaging.services import list_card, post_list_card

    recipients = set(recipient_ids)
    if not recipients.issubset(friend_ids(sender)):
        raise TakeError(400, 'not_friends', 'You can only share lists with your friends.')
    card = list_card(list_item(movie_list, sender, request))
    for recipient_id in sorted(recipients):
        post_list_card(sender, recipient_id, card, note=message)
    return len(recipients)


def comment_item(comment, request=None, viewer=None):
    """One comment: who wrote it, its text and photo, and the comment it
    answers when it is a reply. The list's owner is marked as the writer."""
    return {
        'id': comment.id,
        'author': _user(comment.author, request),
        'body': comment.body,
        'parent_id': comment.parent_id,
        'image_url': comment.image.url if comment.image else None,
        'is_writer': comment.author_id == comment.movie_list.owner_id,
        'is_mine': viewer is not None and comment.author_id == viewer.id,
        'created_at': comment.created_at,
    }


def comments_of(movie_list):
    return movie_list.comments.select_related('author', 'movie_list')


def add_comment(movie_list, author, body, parent=None, image=None):
    return MovieListComment.objects.create(
        movie_list=movie_list, author=author, body=body, parent=parent, image=image,
    )
