import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.shortcuts import render

from films.movie_source import MovieSourceNotConfigured, MovieSourceUnavailable
from films.watchmode import discover_movies

logger = logging.getLogger(__name__)

RANDOM_WALL_SIZE = 50
RANDOM_WALL_CACHE_KEY = 'landing:random-wall'
RANDOM_WALL_CACHE_SECONDS = 60 * 60 * 6


# Shown on the "Pick at random" wall when the popular list can't be fetched.
RANDOM_FILMS = [
    {'title': 'The Long Summer', 'a': '#e0a24b', 'b': '#3b2a14'},
    {'title': 'Neon Harbor', 'a': '#d93fa6', 'b': '#2b1b5f'},
    {'title': 'Quiet Orbit', 'a': '#4ac0a0', 'b': '#1f3b6f'},
    {'title': 'Paper Kings', 'a': '#c86a2a', 'b': '#2a1408'},
    {'title': 'Salt and Ash', 'a': '#a0b04a', 'b': '#3a2a20'},
    {'title': 'Midnight Atlas', 'a': '#5a8ac0', 'b': '#151f3a'},
    {'title': 'Glass Garden', 'a': '#e86fa0', 'b': '#3f5a2c'},
    {'title': 'The Last Ferry', 'a': '#8aa07a', 'b': '#1f2a20'},
    {'title': 'Red Meridian', 'a': '#d6334f', 'b': '#2a0f18'},
    {'title': 'Northbound', 'a': '#7fb6e8', 'b': '#2a3a60'},
    {'title': 'Golden Hour', 'a': '#f1cf72', 'b': '#7a4a20'},
    {'title': 'Static Bloom', 'a': '#b48cf0', 'b': '#2a1a40'},
]


def random_wall_films():
    """The most popular films on Watchmode that have a poster, up to 50, each
    with two colours the wall shows while its poster loads. Cached for a few
    hours; falls back to [RANDOM_FILMS] when Watchmode can't answer."""
    cached = cache.get(RANDOM_WALL_CACHE_KEY)
    if cached:
        return cached
    films = []
    try:
        page = 1
        while len(films) < RANDOM_WALL_SIZE and page <= 4:
            result = discover_movies(page)
            for row in result['results']:
                if row.get('poster_url') and row.get('title'):
                    films.append({'title': row['title'], 'poster': row['poster_url']})
            if page >= result['total_pages']:
                break
            page += 1
    except (MovieSourceNotConfigured, MovieSourceUnavailable):
        logger.warning('Landing: popular films unavailable, using the demo wall.')
    films = films[:RANDOM_WALL_SIZE]
    if len(films) < 8:
        return RANDOM_FILMS
    for i, film in enumerate(films):
        colours = RANDOM_FILMS[i % len(RANDOM_FILMS)]
        film['a'], film['b'] = colours['a'], colours['b']
    cache.set(RANDOM_WALL_CACHE_KEY, films, RANDOM_WALL_CACHE_SECONDS)
    return films


def index(request):
    """The FilmSage landing page: one section per feature of the app."""
    return render(request, 'landing/home.html', {'random_films': random_wall_films()})


def join(request):
    """Send a visitor who clicked "Join" to the FilmSage web app."""
    return HttpResponseRedirect(settings.FILMSAGE_APP_URL)
