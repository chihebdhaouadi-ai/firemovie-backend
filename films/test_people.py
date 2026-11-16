from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from accounts.models import User
from films.tests import fake_upstream

URL = '/api/films/people/nm0000209/'

OVERVIEW = {'data': {'name': {
    '__typename': 'Name',
    'id': 'nm0000209',
    'nameText': {'text': 'Tim Robbins'},
    'primaryImage': {'url': 'https://m.media-amazon.com/images/robbins.jpg'},
    'height': {
        'measurement': {'value': 195.58, 'unit': 'CENTIMETER'},
        'displayableProperty': {'value': {'plainText': '6′ 5″ (1.96 m)'}},
    },
    'bio': {'text': {'plainText': '  Born in West Covina, California.  '}},
    'birthDate': {'date': '1958-10-16'},
    'birthLocation': {'text': 'West Covina, California, USA'},
    'deathDate': None,
}}}


def _title(film_id, title, year, kind='movie', poster='https://img/p.jpg'):
    return {
        'id': film_id,
        'titleText': {'text': title},
        'releaseYear': {'year': year},
        'titleType': {'id': kind},
        'primaryImage': {'url': poster} if poster else None,
    }


KNOWN_FOR = {'data': {'name': {'knownFor': {'edges': [
    {'node': {
        'title': _title('tt0111161', 'The Shawshank Redemption', 1994),
        'credit': {
            '__typename': 'Cast',
            'category': {'id': 'actor', 'text': 'Actor'},
            'characters': [{'name': 'Andy Dufresne'}],
        },
    }},
    {'node': {
        'title': _title('tt0118276', 'Some Series', 2001, kind='tvSeries'),
        'credit': {'__typename': 'Cast', 'category': {'text': 'Actor'}},
    }},
    {'node': {
        'title': _title('tt0112818', 'Dead Man Walking', 1995, poster='http://insecure'),
        'credit': {'__typename': 'Crew', 'category': {'id': 'director', 'text': 'Director'}},
    }},
    {'node': {'title': _title('bad-id', 'Broken', 2000), 'credit': {}}},
    {'node': {
        'title': _title('tt0111161', 'The Shawshank Redemption', 1994),
        'credit': {'__typename': 'Cast'},
    }},
]}}}}

ROUTES = {'get-overview?nm=nm0000209': OVERVIEW, 'get-known-for?nm=nm0000209': KNOWN_FOR}


@override_settings(IMDB232_RAPIDAPI_KEY='test-key')
class PersonDetailTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='alice', email='alice@example.com', password='pw-12345',
        )
        self.client.force_authenticate(self.user)

    def get(self, routes=ROUTES, calls=None, url=URL):
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            return self.client.get(url)

    def test_returns_person_profile_and_known_for_films(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            'person_id': 'nm0000209',
            'name': 'Tim Robbins',
            'photo_url': 'https://m.media-amazon.com/images/robbins.jpg',
            'height': {'cm': 196, 'display': '6′ 5″ (1.96 m)'},
            'biography': 'Born in West Covina, California.',
            'birth_date': '1958-10-16',
            'birth_place': 'West Covina, California, USA',
            'death_date': None,
            'known_for': [
                {
                    'film_id': 'tt0111161',
                    'title': 'The Shawshank Redemption',
                    'year': 1994,
                    'poster_url': 'https://img/p.jpg',
                    'credit_type': 'cast',
                    'job': 'Actor',
                    'characters': ['Andy Dufresne'],
                },
                {
                    'film_id': 'tt0112818',
                    'title': 'Dead Man Walking',
                    'year': 1995,
                    'poster_url': None,
                    'credit_type': 'crew',
                    'job': 'Director',
                    'characters': [],
                },
            ],
        })

    def test_sends_rapidapi_headers_and_caches_the_result(self):
        calls = []
        self.get(calls=calls)
        self.get(calls=calls)
        self.assertEqual(len(calls), 2)
        request = calls[0]
        self.assertIn('imdb232.p.rapidapi.com/api/actors/get-overview?nm=nm0000209', request.full_url)
        self.assertEqual(request.get_header('X-rapidapi-key'), 'test-key')
        self.assertEqual(request.get_header('X-rapidapi-host'), 'imdb232.p.rapidapi.com')

    def test_missing_fields_become_null(self):
        overview = {'data': {'name': {'nameText': {'text': 'Jane Doe'}}}}
        response = self.get({
            'get-overview': overview,
            'get-known-for': {'data': {'name': {'knownFor': None}}},
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['photo_url'])
        self.assertIsNone(response.data['height'])
        self.assertIsNone(response.data['biography'])
        self.assertIsNone(response.data['birth_date'])
        self.assertEqual(response.data['known_for'], [])

    def test_unknown_person_is_404(self):
        response = self.get({'get-overview': {'data': {'name': {'nameText': None}}}})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'person_not_found')

    def test_upstream_404_is_person_not_found(self):
        error = HTTPError('https://imdb232.p.rapidapi.com', 404, 'Not Found', None, None)
        response = self.get({'get-overview': error})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'person_not_found')

    def test_upstream_failure_is_502(self):
        response = self.get({'get-overview': URLError('down')})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'movie_source_unavailable')

    @override_settings(IMDB232_RAPIDAPI_KEY='')
    def test_missing_key_is_503(self):
        with mock.patch('films.movie_source.urlopen') as opener:
            response = self.client.get(URL)
        opener.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'movie_source_not_configured')

    def test_rejects_ids_that_are_not_imdb_names(self):
        self.assertEqual(self.client.get('/api/films/people/12345/').status_code, 404)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(URL).status_code, 401)
