import json
from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from films.models import Film, FilmEntry

TOP5 = 'top5'
WATCHED = 'watched'
WATCHLIST = 'watchlist'


class ListApiTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='alice', email='alice@example.com', password='pw-12345',
        )
        self.other = User.objects.create_user(
            username='bob', email='bob@example.com', password='pw-12345',
        )
        self.client.force_authenticate(self.user)

    def url(self, name, film_id=None):
        paths = {
            TOP5: '/api/lists/top5/',
            WATCHED: '/api/lists/watched/',
            WATCHLIST: '/api/lists/watchlist/',
        }
        base = paths[name]
        return f'{base}{film_id}/' if film_id else base

    def add_top5(self, film_id, **extra):
        return self.client.post(
            self.url(TOP5), {'film_id': film_id, **extra}, format='json',
        )

    def slots(self, user=None):
        entries = FilmEntry.objects.filter(user=user or self.user, list_type='top_5')
        return {entry.slot_index: entry.film_id for entry in entries}


class Top5Tests(ListApiTestCase):
    def test_first_add_takes_lowest_free_slot_and_returns_201(self):
        response = self.add_top5('tt0111161')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['slot'], 1)
        self.assertEqual(response.data['film_id'], 'tt0111161')
        self.assertEqual(response.data['list_type'], 'top_5')

    def test_repeat_add_is_idempotent_and_returns_200(self):
        self.add_top5('tt0111161')
        response = self.add_top5('tt0111161')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FilmEntry.objects.filter(user=self.user, list_type='top_5').count(), 1)

    def test_sixth_film_is_rejected_with_top5_full(self):
        for film_id in ['1', '2', '3', '4', '5']:
            self.assertEqual(self.add_top5(film_id).status_code, 201)
        response = self.add_top5('6')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'top5_full')
        self.assertEqual(len(self.slots()), 5)

    def test_explicit_taken_slot_requires_replace(self):
        self.add_top5('100', slot=2)
        response = self.add_top5('200', slot=2)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'top5_slot_taken')
        self.assertEqual(self.slots(), {2: '100'})

    def test_replace_true_overwrites_occupant(self):
        self.add_top5('100', slot=2)
        response = self.add_top5('200', slot=2, replace=True)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.slots(), {2: '200'})

    def test_slot_out_of_range_is_400(self):
        response = self.add_top5('100', slot=6)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'validation_error')

    def test_invalid_film_id_is_400(self):
        response = self.add_top5('not-an-id')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'validation_error')

    def test_move_swaps_with_occupant(self):
        self.add_top5('100', slot=1)
        self.add_top5('200', slot=2)
        response = self.client.patch(self.url(TOP5, '100'), {'slot': 2}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['slot'], 2)
        self.assertEqual(self.slots(), {1: '200', 2: '100'})

    def test_move_to_empty_slot_keeps_others(self):
        self.add_top5('100', slot=1)
        response = self.client.patch(self.url(TOP5, '100'), {'slot': 4}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.slots(), {4: '100'})

    def test_move_missing_film_is_404(self):
        response = self.client.patch(self.url(TOP5, '100'), {'slot': 3}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'not_in_list')

    def test_delete_returns_204_then_404(self):
        self.add_top5('100')
        self.assertEqual(self.client.delete(self.url(TOP5, '100')).status_code, 204)
        response = self.client.delete(self.url(TOP5, '100'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {'detail': 'Film is not in this list.', 'code': 'not_in_list'})


class WatchedAndWatchlistTests(ListApiTestCase):
    def test_watched_add_returns_201_then_200(self):
        first = self.client.post(self.url(WATCHED), {'film_id': 'tt0111161'}, format='json')
        second = self.client.post(self.url(WATCHED), {'film_id': 'tt0111161'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(FilmEntry.objects.filter(user=self.user, list_type='watched').count(), 1)

    def test_watched_add_removes_from_watchlist_and_reports_it(self):
        self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        response = self.client.post(self.url(WATCHED), {'film_id': '550'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['removed_from_watchlist'])
        self.assertFalse(
            FilmEntry.objects.filter(user=self.user, list_type='watchlist', film_id='550').exists(),
        )

    def test_undo_restores_watchlist_entry(self):
        self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        self.client.post(self.url(WATCHED), {'film_id': '550'}, format='json')
        self.assertEqual(self.client.delete(self.url(WATCHED, '550')).status_code, 204)
        response = self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_watchlist_add_blocked_when_already_watched(self):
        self.client.post(self.url(WATCHED), {'film_id': '550'}, format='json')
        response = self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['code'], 'already_watched')

    def test_watchlist_add_is_idempotent(self):
        first = self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        second = self.client.post(self.url(WATCHLIST), {'film_id': '550'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)

    def test_delete_missing_watchlist_entry_is_404(self):
        response = self.client.delete(self.url(WATCHLIST, '550'))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'not_in_list')

    def test_numeric_film_id_is_accepted_for_list_entries(self):
        self.client.post(self.url(WATCHLIST), {'film_id': '278'}, format='json')
        self.assertEqual(self.client.delete(self.url(WATCHLIST, '278')).status_code, 204)


class ListReadTests(ListApiTestCase):
    def test_collection_is_paginated_and_ordered_by_slot_for_top5(self):
        self.add_top5('300', slot=3)
        self.add_top5('100', slot=1)
        self.add_top5('200', slot=2)
        response = self.client.get(self.url(TOP5))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        self.assertEqual([row['film_id'] for row in response.data['results']], ['100', '200', '300'])

    def test_page_size_is_capped_at_100(self):
        response = self.client.get(self.url(WATCHED), {'page_size': 500})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_counts_endpoint_reports_each_list(self):
        self.add_top5('100')
        self.client.post(self.url(WATCHED), {'film_id': '200'}, format='json')
        self.client.post(self.url(WATCHLIST), {'film_id': '300'}, format='json')
        response = self.client.get('/api/lists/')
        self.assertEqual(response.data, {'top_5': 1, 'watched': 1, 'watchlist': 1})


class UserScopingTests(ListApiTestCase):
    def test_other_users_entries_are_invisible(self):
        self.client.force_authenticate(self.other)
        self.add_top5('100')
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url(TOP5))
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(self.client.get('/api/lists/').data['top_5'], 0)

    def test_cannot_delete_another_users_entry(self):
        self.client.force_authenticate(self.other)
        self.client.post(self.url(WATCHED), {'film_id': '100'}, format='json')
        self.client.force_authenticate(self.user)
        response = self.client.delete(self.url(WATCHED, '100'))
        self.assertEqual(response.status_code, 404)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url(WATCHED)).data['count'], 1)

    def test_same_film_can_live_in_two_users_lists(self):
        self.client.post(self.url(WATCHED), {'film_id': '100'}, format='json')
        self.client.force_authenticate(self.other)
        response = self.client.post(self.url(WATCHED), {'film_id': '100'}, format='json')
        self.assertEqual(response.status_code, 201)

    def test_cannot_reorder_another_users_top5(self):
        # Bob fills slot 1 directly; Alice must not be able to touch it.
        FilmEntry.objects.create(user=self.other, film_id='bob-film',
                                 list_type='top_5', slot_index=1)
        # Alice PATCHes Bob's film -> 404 (not in her list).
        response = self.client.patch(
            self.url(TOP5, 'bob-film'), {'slot': 2}, format='json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.slots(self.other), {1: 'bob-film'})

    def test_collection_add_is_scoped_to_the_authenticated_user(self):
        self.client.post(self.url(WATCHLIST), {'film_id': '101'}, format='json')
        self.client.force_authenticate(self.other)
        self.client.post(self.url(WATCHLIST), {'film_id': '202'}, format='json')
        # Switch back to Alice and confirm she only sees her own entry.
        self.client.force_authenticate(self.user)
        response = self.client.get(self.url(WATCHLIST))
        self.assertEqual(
            {row['film_id'] for row in response.data['results']},
            {'101'},
        )


class AuthenticationTests(APITestCase):
    def test_unauthenticated_requests_get_401(self):
        for path in ['/api/lists/', '/api/lists/top5/', '/api/lists/watched/', '/api/lists/watchlist/']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.data['code'], 'not_authenticated')

    def test_token_authentication_works(self):
        user = User.objects.create_user(username='carol', email='carol@example.com', password='pw-12345')
        token = Token.objects.create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = self.client.post('/api/lists/watched/', {'film_id': '42'}, format='json')
        self.assertEqual(response.status_code, 201)


class LegacyEndpointTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    @override_settings(RAPIDAPI_KEY='')
    def test_legacy_add_and_get_keep_response_shape(self):
        response = self.client.post('/api/film/add_top_5_movies', {'imdbid': 'tt0111161'})
        self.assertEqual(response.data, {'status': 200, 'message': 'MOVIE ADD IT'})
        response = self.client.get('/api/film/get_top_5_movies')
        self.assertEqual(response.data, {
            'data': [{'imdp_id': 'tt0111161', 'title': None, 'poster_url': None}],
            'status': 200,
        })

    @override_settings(OMDB_API_KEY='test-key', RAPIDAPI_KEY='test-key')
    def test_legacy_lists_include_title_and_poster_from_detail(self):
        self.client.post('/api/film/add_watchlist_movies', {'imdbid': 'tt0111161'})
        routes = {
            'i=tt0111161': SHAWSHANK_DETAIL,
            '/shows/': {},
        }
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/film/get_watch_list_movies')
        self.assertEqual(response.data['data'], [{
            'imdp_id': 'tt0111161',
            'title': 'The Shawshank Redemption',
            'poster_url': 'https://img/p.jpg',
        }])

    @override_settings(RAPIDAPI_KEY='test-key')
    def test_legacy_list_still_loads_when_film_source_fails(self):
        self.client.post('/api/film/add_watched_movies', {'imdbid': 'tt0111161'})
        with mock.patch('films.movie_source.urlopen', side_effect=URLError('down')):
            response = self.client.get('/api/film/get_wathced_list_movies')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], [
            {'imdp_id': 'tt0111161', 'title': None, 'poster_url': None},
        ])

    def test_legacy_add_missing_imdbid_is_400(self):
        response = self.client.post('/api/film/add_watched_movies', {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {'status': 400, 'message': 'imdbid required'})

    def test_legacy_watchlist_add_blocked_when_watched(self):
        self.client.post('/api/film/add_watched_movies', {'imdbid': 'tt0111161'})
        response = self.client.post('/api/film/add_watchlist_movies', {'imdbid': 'tt0111161'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['status'], 409)

    def test_legacy_delete_absent_item_still_returns_200(self):
        response = self.client.post('/api/film/delete_watch_list_movies', {'imdbid': 'tt0111161'})
        self.assertEqual(response.data, {'status': 200, 'message': 'MOVIE REMOVED'})

    def test_legacy_popular_counts_across_users(self):
        self.client.post('/api/film/add_watched_movies', {'imdbid': 'tt1'})
        self.client.force_authenticate(self.other)
        self.client.post('/api/film/add_watched_movies', {'imdbid': 'tt1'})
        self.client.post('/api/film/add_watched_movies', {'imdbid': 'tt2'})
        response = self.client.get('/api/film/get_popular_friends_list_movies')
        self.assertEqual(response.data['data'][0]['imdp_id'], 'tt1')
        self.assertEqual(response.data['data'][0]['count'], 2)
        self.assertEqual(response.data['data'][1]['imdp_id'], 'tt2')
        self.assertEqual(response.data['data'][1]['count'], 1)
        self.assertIn('poster_url', response.data['data'][0])


class ErrorShapeTests(ListApiTestCase):
    def test_errors_carry_detail_and_code(self):
        response = self.client.delete(self.url(TOP5, '999'))
        self.assertEqual(set(response.data.keys()), {'detail', 'code'})


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_upstream(routes, calls=None):
    def opener(request, timeout=None):
        url = request.full_url
        if calls is not None:
            calls.append(request)
        for fragment, payload in routes.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload)
        raise AssertionError(f'unexpected upstream call: {url}')
    return opener


SHAWSHANK_SEARCH = {
    'Search': [
        {
            'Title': 'The Shawshank Redemption', 'Year': '1994',
            'imdbID': 'tt0111161', 'Type': 'movie', 'Poster': 'https://img/p.jpg',
        },
        {
            'Title': 'Some Show', 'Year': '2011', 'imdbID': 'tt0944947',
            'Type': 'series', 'Poster': 'N/A',
        },
    ],
    'totalResults': '1',
    'Response': 'True',
}

SHAWSHANK_DETAIL = {
    'Title': 'The Shawshank Redemption',
    'Year': '1994',
    'Runtime': '142 min',
    'Genre': 'Drama',
    'Director': 'Frank Darabont',
    'Poster': 'https://img/p.jpg',
    'imdbRating': '9.3',
    'Plot': 'Hope.',
    'Response': 'True',
}


@override_settings(OMDB_API_KEY='test-key', RAPIDAPI_KEY='test-key')
class CatalogTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def search(self, query, routes, calls=None, **params):
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            return self.client.get('/api/films/search', {'q': query, **params})

    def test_search_requires_two_characters(self):
        response = self.client.get('/api/films/search', {'q': 'a'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'query_too_short')

    def test_search_keeps_only_movies_and_reports_in_lists(self):
        FilmEntry.objects.create(user=self.user, film_id='tt0111161', list_type='watched')
        response = self.search('shaw', {'s=shaw&page=1': SHAWSHANK_SEARCH})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        result = response.data['results'][0]
        self.assertEqual(result['film_id'], 'tt0111161')
        self.assertEqual(result['title'], 'The Shawshank Redemption')
        self.assertEqual(result['year'], 1994)
        self.assertEqual(result['poster_url'], 'https://img/p.jpg')
        self.assertEqual(result['in_lists'], ['watched'])

    def test_search_sends_omdb_query_parameters(self):
        calls = []
        self.search('joker', {'s=joker&page=1': {
            'Search': [], 'totalResults': '0', 'Response': 'True',
        }}, calls)
        request = calls[0]
        self.assertEqual(request.full_url, 'https://www.omdbapi.com/?apikey=test-key&s=joker&page=1')
        self.assertIsNone(request.get_header('X-rapidapi-key'))

    def test_search_uses_requested_page_and_reports_pagination(self):
        calls = []
        second_page = {
            'Search': [{
                'Title': 'Second page film', 'Year': '2000', 'imdbID': 'tt0000002',
                'Type': 'movie', 'Poster': 'N/A',
            }],
            'totalResults': '21',
            'Response': 'True',
        }
        response = self.search('joker', {'s=joker&page=2': second_page}, calls, page=2)
        self.assertEqual(response.data['page'], 2)
        self.assertEqual(response.data['total_pages'], 3)
        self.assertEqual(response.data['total_results'], 21)
        self.assertEqual(response.data['results'][0]['film_id'], 'tt0000002')
        self.assertIn('page=2', calls[0].full_url)

    def test_search_no_match_keeps_success_response_shape(self):
        response = self.search('no match', {
            's=no+match&page=1': {'Response': 'False', 'Error': 'Movie not found!'},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            'page': 1, 'total_pages': 1, 'total_results': 0, 'results': [],
        })

    def test_search_responses_are_cached(self):
        calls = []
        routes = {'s=joker&page=1': {
            'Search': [], 'totalResults': '0', 'Response': 'True',
        }}
        self.search('joker', routes, calls)
        self.search('joker', routes, calls)
        self.assertEqual(len(calls), 1)

    def test_invalid_page_is_400(self):
        response = self.client.get('/api/films/search', {'q': 'joker', 'page': 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'validation_error')

    def test_missing_key_returns_503(self):
        with override_settings(OMDB_API_KEY=''):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'movie_source_not_configured')

    def test_network_failure_returns_502(self):
        with mock.patch('films.movie_source.urlopen', side_effect=URLError('down')):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'movie_source_unavailable')

    def test_omdb_rejected_key_returns_502(self):
        routes = {'s=joker&page=1': {'Response': 'False', 'Error': 'Invalid API key!'}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 502)

    def test_detail_uses_omdb_fields_and_request_parameters(self):
        calls = []
        routes = {'i=tt0111161': SHAWSHANK_DETAIL, '/shows/': {}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['film_id'], 'tt0111161')
        self.assertEqual(response.data['title'], 'The Shawshank Redemption')
        self.assertEqual(response.data['runtime'], 142)
        self.assertEqual(response.data['genres'], ['Drama'])
        self.assertEqual(response.data['director'], 'Frank Darabont')
        self.assertEqual(response.data['rating'], 9.3)
        self.assertEqual(response.data['overview'], 'Hope.')
        self.assertEqual(response.data['poster_url'], 'https://img/p.jpg')
        self.assertEqual(response.data['in_lists'], [])
        request = calls[0]
        self.assertEqual(
            request.full_url,
            'https://www.omdbapi.com/?apikey=test-key&i=tt0111161&plot=full',
        )

    def test_detail_for_unknown_imdb_id_is_404(self):
        routes = {'i=tt9999999': {'Response': 'False', 'Error': 'Movie not found!'}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/films/tt9999999/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'film_not_found')

    def test_detail_without_title_payload_is_404(self):
        routes = {'i=tt0111161': {'Response': 'False', 'Error': 'Movie not found!'}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 404)

    def test_detail_upstream_failure_returns_502(self):
        with mock.patch('films.movie_source.urlopen', side_effect=TimeoutError()):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 502)

    def test_detail_missing_key_returns_503(self):
        with override_settings(OMDB_API_KEY=''):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 503)

    def test_detail_responses_are_cached(self):
        calls = []
        routes = {'i=tt0111161': SHAWSHANK_DETAIL, '/shows/': {}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            self.client.get('/api/films/tt0111161/')
            self.client.get('/api/films/tt0111161/')
        self.assertEqual(len(calls), 2)

    def test_detail_rejects_numeric_ids(self):
        response = self.client.get('/api/films/278/')
        self.assertEqual(response.status_code, 404)

    def test_stills_keep_only_landscape_still_frames(self):
        images = {'images': [
            {'type': 'still_frame', 'url': 'https://img/s1.jpg', 'width': 640, 'height': 420},
            {'type': 'still_frame', 'url': 'https://img/portrait.jpg', 'width': 300, 'height': 450},
            {'type': 'poster', 'url': 'https://img/p.jpg', 'width': 1200, 'height': 1800},
        ]}
        routes = {'/title/get-images': images}
        calls = []
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            response = self.client.get('/api/films/tt0111161/stills/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['stills'], ['https://img/s1.jpg'])
        request = calls[0]
        self.assertIn('online-movie-database.p.rapidapi.com/title/get-images', request.full_url)
        self.assertEqual(request.get_header('X-rapidapi-key'), 'test-key')
        self.assertEqual(
            request.get_header('X-rapidapi-host'),
            'online-movie-database.p.rapidapi.com',
        )


def streaming_option(service_id, name, link, images=None):
    return {'link': link, 'service': {'id': service_id, 'name': name, 'imageSet': images or {}}}


STREAMING_OPTIONS = [
    streaming_option('apple', 'Apple TV', 'https://tv.apple/x', {
        'darkThemeImage': 'https://img/apple-dark.png',
        'lightThemeImage': 'https://img/apple-light.png',
    }),
    streaming_option('prime', 'Amazon Prime Video', 'https://amazon/x', {
        'lightThemeImage': 'https://img/prime.png',
    }),
    streaming_option('prime', 'Amazon Prime Video', 'https://amazon/y'),
    streaming_option('tubi', 'Tubi', 'https://tubi/x'),
    streaming_option('plutotv', 'Pluto TV', 'http://insecure/x'),
    streaming_option('', 'No id', 'https://blank/x'),
]


@override_settings(OMDB_API_KEY='test-key', RAPIDAPI_KEY='test-key', STREAMING_COUNTRY='us')
class WatchProvidersTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def detail(self, show, calls=None):
        routes = {
            'i=tt0111161': SHAWSHANK_DETAIL,
            '/shows/': show,
        }
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            return self.client.get('/api/films/tt0111161/')

    def test_platforms_are_listed_once_per_service_for_region_only(self):
        show = {'streamingOptions': {
            'us': STREAMING_OPTIONS,
            'ca': [streaming_option('roku', 'Roku Channel', 'https://roku/x')],
        }}
        providers = self.detail(show).data['watch_providers']
        self.assertEqual(providers, {
            'link': None,
            'available': [
                {'name': 'Apple TV', 'logo_url': 'https://img/apple-dark.png', 'url': 'https://tv.apple/x'},
                {'name': 'Amazon Prime Video', 'logo_url': 'https://img/prime.png', 'url': 'https://amazon/x'},
                {'name': 'Tubi', 'logo_url': None, 'url': 'https://tubi/x'},
            ],
        })

    def test_request_uses_rapidapi_key_host_and_country(self):
        calls = []
        self.detail({}, calls)
        request = [call for call in calls if '/shows/' in call.full_url][0]
        self.assertIn('streaming-availability.p.rapidapi.com/shows/tt0111161', request.full_url)
        self.assertIn('country=us', request.full_url)
        self.assertEqual(request.get_header('X-rapidapi-key'), 'test-key')
        self.assertEqual(request.get_header('X-rapidapi-host'), 'streaming-availability.p.rapidapi.com')

    def test_streaming_outage_still_returns_detail_with_no_providers(self):
        response = self.detail(TimeoutError())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'The Shawshank Redemption')
        self.assertEqual(response.data['watch_providers']['available'], [])

    def test_unknown_title_has_no_providers(self):
        error = HTTPError('https://streaming-availability.p.rapidapi.com', 404, 'Not Found', None, None)
        response = self.detail(error)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['watch_providers']['available'], [])

    def test_streaming_options_are_cached(self):
        calls = []
        self.detail({}, calls)
        self.detail({}, calls)
        titles = [call for call in calls if '/shows/' in call.full_url]
        self.assertEqual(len(titles), 1)


class CatalogAuthTests(APITestCase):
    def test_catalog_requires_authentication(self):
        self.assertEqual(self.client.get('/api/films/search', {'q': 'joker'}).status_code, 401)
        self.assertEqual(self.client.get('/api/films/tt0111161/').status_code, 401)


@override_settings(OMDB_API_KEY='test-key', RAPIDAPI_KEY='test-key')
class FilmRecordTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.routes = {
            'i=tt0111161': SHAWSHANK_DETAIL,
            '/shows/': {},
        }

    def upstream(self, calls=None):
        return mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(self.routes, calls))

    def test_detail_is_saved_and_read_back_without_film_upstream_calls(self):
        with self.upstream():
            self.client.get('/api/films/tt0111161/')
        cache.clear()
        calls = []
        with self.upstream(calls):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.data['title'], 'The Shawshank Redemption')
        self.assertTrue(all('/shows/' in call.full_url for call in calls))
        film = Film.objects.get(imdb_id='tt0111161')
        self.assertEqual(film.title, 'The Shawshank Redemption')
        self.assertEqual(film.director, 'Frank Darabont')
        self.assertEqual(film.genres, ['Drama'])

    def test_take_saves_film_record(self):
        self.client.put('/api/takes/films/tt0111161/reaction/', {'reaction': 'loved'}, format='json')
        with self.upstream():
            response = self.client.post(
                '/api/takes/films/tt0111161/takes/', {'body': 'Great'}, format='json',
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Film.objects.get(imdb_id='tt0111161').title, 'The Shawshank Redemption')

    def test_take_is_created_when_film_source_is_down(self):
        self.client.put('/api/takes/films/tt0111161/reaction/', {'reaction': 'loved'}, format='json')
        with mock.patch('films.movie_source.urlopen', side_effect=URLError('down')):
            response = self.client.post(
                '/api/takes/films/tt0111161/takes/', {'body': 'Great'}, format='json',
            )
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Film.objects.exists())

    def test_review_saves_film_record(self):
        with self.upstream():
            response = self.client.post(
                '/api/review/add_review', {'imdb_id': 'tt0111161', 'rating': 5, 'body': 'Great'},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Film.objects.get(imdb_id='tt0111161').title, 'The Shawshank Redemption')

    def test_review_with_malformed_imdb_id_does_not_call_film_source(self):
        with mock.patch('films.movie_source.urlopen') as opener:
            response = self.client.post(
                '/api/review/add_review', {'imdb_id': 'not-an-id', 'rating': 3},
            )
        self.assertEqual(response.status_code, 200)
        opener.assert_not_called()


class PopularThisWeekTests(APITestCase):
    url = '/api/films/popular/'

    def setUp(self):
        from django.core.cache import cache
        from django.contrib.auth import get_user_model
        from datetime import timedelta
        from django.utils import timezone
        from .models import Film, FilmEntry

        cache.clear()
        self._timedelta = timedelta
        self._timezone = timezone
        self._FilmEntry = FilmEntry
        User = get_user_model()
        self.users = [
            User.objects.create_user(username=f'pop{i}', password='pw-123456')
            for i in range(4)
        ]
        self.client.force_authenticate(self.users[0])
        Film.objects.create(imdb_id='tt0000001', title='Blockbuster', year=2020, poster_url='p1')
        Film.objects.create(imdb_id='tt0000002', title='Cult', year=1999, poster_url='p2')

    def add(self, user, film_id, list_type, days_ago=0):
        entry = self._FilmEntry.objects.create(
            user=user, film_id=film_id, list_type=list_type,
            slot_index=1 if list_type == 'top_5' else None,
        )
        self._FilmEntry.objects.filter(pk=entry.pk).update(
            created_at=self._timezone.now() - self._timedelta(days=days_ago),
        )

    def test_counts_watched_and_watchlist_adds_from_the_last_week_only(self):
        self.add(self.users[0], 'tt0000001', 'watched')
        self.add(self.users[1], 'tt0000001', 'watchlist')
        self.add(self.users[2], 'tt0000001', 'watched', days_ago=8)  # too old
        self.add(self.users[0], 'tt0000002', 'watched')
        self.add(self.users[3], 'tt0000002', 'top_5')  # top 5 does not count

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {'film_id': 'tt0000001', 'title': 'Blockbuster', 'year': 2020,
                 'poster_url': 'p1', 'adds': 2},
                {'film_id': 'tt0000002', 'title': 'Cult', 'year': 1999,
                 'poster_url': 'p2', 'adds': 1},
            ],
        )

    def test_orders_by_adds_then_most_recent(self):
        self.add(self.users[0], 'tt0000002', 'watched', days_ago=2)
        self.add(self.users[1], 'tt0000001', 'watched', days_ago=3)
        self.add(self.users[2], 'tt0000002', 'watched', days_ago=1)

        ids = [row['film_id'] for row in self.client.get(self.url).json()]
        self.assertEqual(ids, ['tt0000002', 'tt0000001'])

    def test_fetches_details_for_popular_films_not_stored_yet(self):
        from unittest import mock
        from .models import Film

        Film.objects.filter(imdb_id='tt0000002').delete()
        self.add(self.users[0], 'tt0000002', 'watchlist')
        fetched = Film(imdb_id='tt0000002', title='Fetched', year=2001, poster_url='p3')

        with mock.patch('films.catalog_views.try_stored_film', return_value=fetched) as fetch:
            body = self.client.get(self.url).json()

        fetch.assert_called_once_with('tt0000002')
        self.assertEqual(body[0]['title'], 'Fetched')

    def test_skips_films_whose_details_cannot_be_loaded(self):
        from unittest import mock
        from .models import Film

        Film.objects.filter(imdb_id='tt0000002').delete()
        self.add(self.users[0], 'tt0000002', 'watchlist')

        with mock.patch('films.catalog_views.try_stored_film', return_value=None):
            body = self.client.get(self.url).json()

        self.assertEqual(body, [])

    def test_requires_login(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)


WATCHMODE_TITLES = {
    'titles': [
        {'id': 1, 'title': 'The Shawshank Redemption', 'year': 1994,
         'imdb_id': 'tt0111161', 'type': 'movie'},
        {'id': 2, 'title': 'No Imdb Id', 'year': 1994, 'imdb_id': None, 'type': 'movie'},
        {'id': 3, 'title': 'Stored Film', 'year': 1994, 'imdb_id': 'tt0000003', 'type': 'movie'},
    ],
    'page': 1,
    'total_results': 40,
    'total_pages': 2,
}

WATCHMODE_SOURCES = [
    {'id': 203, 'name': 'Netflix', 'type': 'sub', 'logo_100px': 'https://cdn.watchmode.com/n.jpg'},
    {'id': 26, 'name': 'Amazon Prime', 'type': 'sub', 'logo_100px': 'http://insecure/a.jpg'},
    {'id': 204, 'name': 'Netflix', 'type': 'sub', 'logo_100px': None},
    {'name': 'Broken row'},
]


@override_settings(WATCHMODE_API_KEY='wm-key', OMDB_API_KEY='test-key', STREAMING_COUNTRY='us')
class BrowseTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        Film.objects.create(imdb_id='tt0000003', title='Stored Film', poster_url='https://img/stored.jpg')
        self.routes = {
            '/list-titles/': WATCHMODE_TITLES,
            '/sources/': WATCHMODE_SOURCES,
            'i=tt0111161': SHAWSHANK_DETAIL,
        }

    def get(self, path, calls=None, **params):
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(self.routes, calls)):
            return self.client.get(path, params)

    def test_browse_keeps_imdb_films_with_posters_and_in_lists(self):
        FilmEntry.objects.create(user=self.user, film_id='tt0111161', list_type='watchlist')
        response = self.get('/api/films/browse/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_pages'], 2)
        self.assertEqual(response.data['results'], [
            {'film_id': 'tt0111161', 'title': 'The Shawshank Redemption', 'year': 1994,
             'poster_url': 'https://img/p.jpg', 'in_lists': ['watchlist']},
            {'film_id': 'tt0000003', 'title': 'Stored Film', 'year': 1994,
             'poster_url': 'https://img/stored.jpg', 'in_lists': []},
        ])

    def test_stored_posters_skip_omdb(self):
        calls = []
        self.get('/api/films/browse/', calls)
        self.assertFalse(any('i=tt0000003' in call.full_url for call in calls))

    def test_browse_passes_year_and_service_filters(self):
        calls = []
        self.get('/api/films/browse/', calls, year=1994, provider=203, page=2)
        url = next(call.full_url for call in calls if '/list-titles/' in call.full_url)
        for part in ('types=movie', 'sort_by=popularity_desc', 'release_date_start=19940101',
                     'release_date_end=19941231', 'source_ids=203', 'regions=US', 'page=2'):
            self.assertIn(part, url)
        request = next(call for call in calls if '/list-titles/' in call.full_url)
        self.assertEqual(request.get_header('X-api-key'), 'wm-key')
        self.assertNotIn('wm-key', url)

    def test_browse_rejects_bad_filters(self):
        for params in ({'year': 1800}, {'year': 'abc'}, {'provider': 0}, {'genre': -1},
                       {'language': 'eng'}, {'country': 'U1'}):
            response = self.client.get('/api/films/browse/', params)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data['code'], 'invalid_browse_filter')

    def test_posters_are_cached_between_lists(self):
        self.get('/api/films/browse/')
        calls = []
        self.get('/api/films/browse/', calls, year=2000)
        self.assertFalse(any('omdbapi' in call.full_url for call in calls))

    def test_watchmode_error_body_is_502(self):
        self.routes['/list-titles/'] = {'success': False, 'errorMessage': 'Please enter a valid API key.'}
        self.assertEqual(self.get('/api/films/browse/').status_code, 502)

    def test_services_are_unique_named_with_https_logos(self):
        calls = []
        response = self.get('/api/films/providers/', calls)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [
            {'id': 203, 'name': 'Netflix', 'logo_url': 'https://cdn.watchmode.com/n.jpg'},
            {'id': 26, 'name': 'Amazon Prime', 'logo_url': None},
        ])
        self.assertIn('regions=US', calls[0].full_url)
        self.assertIn('types=sub', calls[0].full_url)

    def test_browse_passes_genre_language_and_country(self):
        calls = []
        self.get('/api/films/browse/', calls, genre=11, language='KO', country='fr')
        url = next(call.full_url for call in calls if '/list-titles/' in call.full_url)
        for part in ('genres=11', 'languages=ko', 'regions=FR'):
            self.assertIn(part, url)

    def test_genres_leave_out_tv_only_and_sort_by_name(self):
        self.routes['/genres/'] = [
            {'id': 11, 'name': 'Horror'}, {'id': 23, 'name': 'Reality'},
            {'id': 1, 'name': 'Action'}, {'name': 'Broken'},
        ]
        response = self.get('/api/films/genres/')
        self.assertEqual(response.data, [{'id': 1, 'name': 'Action'}, {'id': 11, 'name': 'Horror'}])

    def test_countries_are_only_plan_enabled(self):
        self.routes['/regions/'] = [
            {'country': 'US', 'name': 'USA', 'flag': 'https://cdn/us.png', 'plan_enabled': True},
            {'country': 'GB', 'name': 'Great Britain', 'flag': 'https://cdn/gb.png', 'plan_enabled': False},
            {'country': 'fr', 'name': 'France', 'flag': None, 'plan_enabled': True},
        ]
        response = self.get('/api/films/countries/')
        self.assertEqual(response.data, [
            {'code': 'US', 'name': 'USA', 'flag_url': 'https://cdn/us.png'},
            {'code': 'FR', 'name': 'France', 'flag_url': None},
        ])

    def test_browse_without_key_is_503(self):
        with override_settings(WATCHMODE_API_KEY=''):
            response = self.client.get('/api/films/browse/')
        self.assertEqual(response.status_code, 503)

    def test_browse_requires_authentication(self):
        self.client.logout()
        self.assertEqual(self.client.get('/api/films/browse/').status_code, 401)
        self.assertEqual(self.client.get('/api/films/providers/').status_code, 401)


WATCHMODE_DETAILS = {
    'id': 1,
    'title': 'The Shawshank Redemption',
    'trailer': 'https://www.youtube.com/watch?v=abc',
    'cast': [
        {'type': 'Crew', 'full_name': 'Stunt Person', 'role': 'Stunts', 'order': 1},
        {'type': 'Cast', 'full_name': 'Morgan Freeman', 'role': 'Red', 'order': 2},
        {'type': 'Cast', 'full_name': 'Tim Robbins', 'role': 'Andy', 'order': 1},
        {'type': 'Crew', 'full_name': 'Thomas Newman', 'role': 'Original Music Composer', 'order': 1},
        {'type': 'Crew', 'full_name': 'Frank Darabont', 'role': 'Screenplay, Director, Stunts', 'order': 1},
        {'type': 'Crew', 'full_name': 'Frank Darabont', 'role': 'Director', 'order': 1},
    ],
    'sources': [
        {'source_id': 26, 'name': 'Amazon', 'type': 'rent', 'web_url': 'https://amazon/r', 'price': 3.99},
        {'source_id': 203, 'name': 'Netflix', 'type': 'sub', 'web_url': 'https://netflix/t', 'price': None},
        {'source_id': 203, 'name': 'Netflix', 'type': 'sub', 'web_url': 'https://netflix/t2'},
        {'source_id': 9, 'name': 'Insecure', 'type': 'sub', 'web_url': 'http://x'},
    ],
}


@override_settings(WATCHMODE_API_KEY='wm-key', OMDB_API_KEY='test-key', RAPIDAPI_KEY='', STREAMING_COUNTRY='us')
class FilmExtrasTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.routes = {
            '/title/tt0111161/details/': WATCHMODE_DETAILS,
            '/sources/': [{'id': 203, 'name': 'Netflix', 'logo_100px': 'https://cdn/n.jpg'}],
            'i=tt0111161': SHAWSHANK_DETAIL,
        }

    def detail(self, calls=None):
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(self.routes, calls)):
            return self.client.get('/api/films/tt0111161/')

    def test_detail_has_trailer_cast_crew_and_watchmode_sources(self):
        data = self.detail().data
        self.assertEqual(data['trailer_url'], 'https://www.youtube.com/watch?v=abc')
        self.assertEqual(data['cast'], [
            {'name': 'Tim Robbins', 'role': 'Andy', 'person_id': None},
            {'name': 'Morgan Freeman', 'role': 'Red', 'person_id': None},
        ])
        self.assertEqual(data['crew'], [
            {'name': 'Frank Darabont', 'job': 'Director, Screenplay', 'person_id': None},
            {'name': 'Thomas Newman', 'job': 'Original Music Composer', 'person_id': None},
        ])
        self.assertEqual(data['watch_providers']['available'], [
            {'name': 'Netflix', 'type': 'sub', 'url': 'https://netflix/t',
             'logo_url': 'https://cdn/n.jpg', 'price': None},
            {'name': 'Amazon', 'type': 'rent', 'url': 'https://amazon/r',
             'logo_url': None, 'price': 3.99},
        ])

    def test_details_request_asks_for_sources_and_cast_in_region(self):
        calls = []
        self.detail(calls)
        url = next(c.full_url for c in calls if '/details/' in c.full_url)
        self.assertIn('append_to_response=sources%2Ccast-crew', url)
        self.assertIn('regions=US', url)

    def test_extras_are_cached(self):
        self.detail()
        calls = []
        self.detail(calls)
        self.assertFalse(any('watchmode' in c.full_url for c in calls))

    def test_detail_has_the_watchmode_backdrop(self):
        self.routes['/title/tt0111161/details/'] = {**WATCHMODE_DETAILS, 'backdrop': 'https://img/b.jpg'}
        self.assertEqual(self.detail().data['backdrop_url'], 'https://img/b.jpg')

    def test_stills_fall_back_to_the_backdrop_when_images_fail(self):
        self.routes['/title/tt0111161/details/'] = {**WATCHMODE_DETAILS, 'backdrop': 'https://img/b.jpg'}
        self.routes['get-images'] = URLError('not subscribed')
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(self.routes)):
            with override_settings(RAPIDAPI_KEY='test-key'):
                response = self.client.get('/api/films/tt0111161/stills/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['stills'], ['https://img/b.jpg'])

    def test_detail_still_opens_when_watchmode_fails(self):
        self.routes['/title/tt0111161/details/'] = {'success': False}
        data = self.detail().data
        self.assertEqual(data['title'], 'The Shawshank Redemption')
        self.assertEqual((data['trailer_url'], data['cast'], data['crew']), (None, [], []))
        self.assertEqual(data['watch_providers'], {'link': None, 'available': []})


@override_settings(KINOCHECK_ENABLED=True, WATCHMODE_API_KEY='', OMDB_API_KEY='test-key', RAPIDAPI_KEY='')
class TrailerTests(ListApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.routes = {
            'i=tt0111161': SHAWSHANK_DETAIL,
            'kinocheck.com/movies?imdb_id=tt0111161': {
                'trailer': {'youtube_video_id': 'tc-TXxekXWo', 'title': 'Trailer'},
            },
        }

    def detail(self, calls=None):
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(self.routes, calls)):
            return self.client.get('/api/films/tt0111161/')

    def test_kinocheck_supplies_the_trailer_video_id(self):
        calls = []
        data = self.detail(calls).data
        kinocheck = next(c for c in calls if 'kinocheck' in c.full_url)
        self.assertEqual(kinocheck.get_header('User-agent'), 'FilmSage/1.0')
        self.assertEqual(data['trailer_youtube_id'], 'tc-TXxekXWo')
        self.assertEqual(data['trailer_url'], 'https://www.youtube.com/watch?v=tc-TXxekXWo')

    def test_trailer_lookup_is_cached_even_when_missing(self):
        self.routes['kinocheck.com/movies?imdb_id=tt0111161'] = {'trailer': None, 'videos': []}
        self.assertIsNone(self.detail().data['trailer_youtube_id'])
        calls = []
        self.detail(calls)
        self.assertFalse(any('kinocheck' in c.full_url for c in calls))

    def test_kinocheck_outage_does_not_break_the_page(self):
        self.routes['kinocheck.com/movies?imdb_id=tt0111161'] = URLError('down')
        data = self.detail().data
        self.assertEqual(data['title'], 'The Shawshank Redemption')
        self.assertIsNone(data['trailer_youtube_id'])

    def test_youtube_id_reads_common_link_shapes(self):
        from films.trailers import youtube_id
        for url in ('https://www.youtube.com/watch?v=tc-TXxekXWo&t=3',
                    'https://youtu.be/tc-TXxekXWo', 'https://www.youtube.com/embed/tc-TXxekXWo'):
            self.assertEqual(youtube_id(url), 'tc-TXxekXWo')
        for url in (None, 'https://vimeo.com/123', 'https://www.youtube.com/watch?v=bad'):
            self.assertIsNone(youtube_id(url))
