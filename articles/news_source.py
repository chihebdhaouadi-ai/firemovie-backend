import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from rest_framework.exceptions import APIException

NEWS_HOST = 'imdb232.p.rapidapi.com'
NEWS_PATH = '/api/news/get-by-category'
NEWS_CATEGORY = 'MOVIE'
NEWS_LIMIT = 25
CACHE_KEY = 'articles:imdb232:movie-news'
NEWS_ID = re.compile(r'ni(\d{1,18})')


class NewsUnavailable(APIException):
    status_code = 502
    default_code = 'news_unavailable'
    default_detail = 'News is temporarily unavailable. Try again.'


def _fetch():
    query = urlencode({'category': NEWS_CATEGORY, 'limit': NEWS_LIMIT})
    request = Request(f'https://{NEWS_HOST}{NEWS_PATH}?{query}', headers={
        'x-rapidapi-key': settings.IMDB232_RAPIDAPI_KEY,
        'x-rapidapi-host': NEWS_HOST,
    })
    try:
        with urlopen(request, timeout=settings.RAPIDAPI_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError) as exc:
        raise NewsUnavailable() from exc


def _https(value):
    return value if isinstance(value, str) and value.startswith('https://') else None


def _card(edge):
    node = (edge or {}).get('node') or {}
    match = NEWS_ID.fullmatch(str(node.get('id') or ''))
    title = ((node.get('articleTitle') or {}).get('plainText') or '').strip()
    cover = _https((node.get('image') or {}).get('url'))
    url = _https(node.get('externalUrl'))
    published_at = node.get('date')
    if not (match and title and cover and url and published_at):
        return None
    return {
        'id': int(match.group(1)),
        'title': title,
        'cover_url': cover,
        'url': url,
        'published_at': published_at,
    }


def latest_movie_news():
    """Movie news cards, newest first, in the shape the app's article list reads."""
    if not settings.IMDB232_RAPIDAPI_KEY:
        return []
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    data = _fetch() or {}
    edges = (((data.get('data') or {}).get('news') or {}).get('edges')) or []
    if not isinstance(edges, list):
        raise NewsUnavailable()
    cards = [card for card in (_card(edge) for edge in edges) if card]

    cache.set(CACHE_KEY, cards, settings.NEWS_CACHE_SECONDS)
    return cards
