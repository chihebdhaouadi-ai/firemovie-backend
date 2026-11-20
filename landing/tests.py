import json
import re
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from films.movie_source import MovieSourceUnavailable
from landing.views import RANDOM_FILMS, random_wall_films


def _page(page, count=20, total_pages=3):
    return {
        'page': page,
        'total_pages': total_pages,
        'results': [
            {'film_id': f'tt{page:02d}{i:05d}', 'title': f'Film {page}-{i}',
             'poster_url': None if i == 0 else f'https://img.test/{page}-{i}.jpg'}
            for i in range(count)
        ],
    }


@patch('landing.views.discover_movies', side_effect=lambda page: _page(page))
class LandingPageTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_home_shows_every_feature_section(self, _discover):
        response = self.client.get(reverse('landing:index'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'landing/home.html')
        for section in ('takes', 'topics', 'friends', 'inbox', 'collections', 'random', 'discover'):
            self.assertContains(response, f'id="{section}"')
        self.assertContains(response, reverse('landing:join'))

    def test_home_opens_with_the_cinematic_intro(self, _discover):
        response = self.client.get(reverse('landing:index'))

        self.assertContains(response, 'id="intro"')
        self.assertContains(response, 'Softseek Corporation')
        self.assertContains(response, 'Cinema is art')

    def test_random_wall_films_are_embedded_safely_as_json(self, _discover):
        response = self.client.get(reverse('landing:index'))

        match = re.search(
            r'<script id="random-films" type="application/json">(.*?)</script>',
            response.content.decode(),
            re.S,
        )
        self.assertIsNotNone(match)
        films = json.loads(match.group(1))
        self.assertEqual(len(films), 50)
        self.assertTrue(all({'title', 'poster', 'a', 'b'} <= film.keys() for film in films))

    @override_settings(FILMSAGE_APP_URL='https://app.example.test')
    def test_join_sends_visitors_to_the_app(self, _discover):
        response = self.client.get(reverse('landing:join'))

        self.assertRedirects(response, 'https://app.example.test', fetch_redirect_response=False)


class RandomWallTests(TestCase):
    def setUp(self):
        cache.clear()

    @patch('landing.views.discover_movies', side_effect=lambda page: _page(page))
    def test_takes_the_50_most_popular_films_with_posters_and_caches_them(self, discover):
        films = random_wall_films()

        self.assertEqual(len(films), 50)
        # Films without a poster are skipped, order is kept.
        self.assertEqual(films[0]['title'], 'Film 1-1')
        self.assertTrue(all(film['poster'] for film in films))
        self.assertEqual(discover.call_count, 3)

        random_wall_films()
        self.assertEqual(discover.call_count, 3)

    @patch('landing.views.discover_movies', side_effect=MovieSourceUnavailable())
    def test_falls_back_to_the_demo_wall_when_watchmode_fails(self, _discover):
        self.assertEqual(random_wall_films(), RANDOM_FILMS)
