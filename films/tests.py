import json
from unittest import mock
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import User
from films.models import FilmEntry

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
    def test_legacy_add_and_get_keep_response_shape(self):
        response = self.client.post('/api/film/add_top_5_movies', {'imdbid': 'tt0111161'})
        self.assertEqual(response.data, {'status': 200, 'message': 'MOVIE ADD IT'})
        response = self.client.get('/api/film/get_top_5_movies')
        self.assertEqual(response.data, {'data': [{'imdp_id': 'tt0111161'}], 'status': 200})

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
        self.assertEqual(response.data['data'][0], {'imdp_id': 'tt1', 'count': 2})
        self.assertEqual(response.data['data'][1], {'imdp_id': 'tt2', 'count': 1})


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


SHAWSHANK_FIND = {'results': [
    {
        'id': '/title/tt0111161/', 'titleType': 'movie', 'year': 1994,
        'title': 'The Shawshank Redemption', 'image': {'url': 'https://img/p.jpg'},
    },
    {'id': '/title/tt0944947/', 'titleType': 'tvSeries', 'title': 'Some Show'},
]}

SHAWSHANK_OVERVIEW = {'title': {
    'title': 'The Shawshank Redemption', 'year': 1994,
    'plot': {'plotText': {'plainText': 'Hope.'}},
    'runtime': {'seconds': 8520},
    'genres': {'genres': [{'text': 'Drama'}]},
    'primaryImage': {'url': 'https://img/p.jpg'},
    'ratingsSummary': {'aggregateRating': 9.3},
}}

SHAWSHANK_CREDITS = {'crew': {'director': [{'name': 'Frank Darabont'}]}}


@override_settings(RAPIDAPI_KEY='test-key')
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
        response = self.search('shaw', {'/title/v2/find': SHAWSHANK_FIND})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        result = response.data['results'][0]
        self.assertEqual(result['film_id'], 'tt0111161')
        self.assertEqual(result['title'], 'The Shawshank Redemption')
        self.assertEqual(result['year'], 1994)
        self.assertEqual(result['poster_url'], 'https://img/p.jpg')
        self.assertEqual(result['in_lists'], ['watched'])

    def test_search_sends_key_header_and_title_without_key_in_url(self):
        calls = []
        self.search('joker', {'/title/v2/find': {'results': []}}, calls)
        request = calls[0]
        self.assertEqual(request.get_header('X-rapidapi-key'), 'test-key')
        self.assertEqual(request.get_header('X-rapidapi-host'), 'online-movie-database.p.rapidapi.com')
        self.assertIn('title=joker', request.full_url)
        self.assertNotIn('test-key', request.full_url)

    def test_later_pages_are_empty_without_upstream_call(self):
        calls = []
        response = self.search('joker', {'/title/v2/find': SHAWSHANK_FIND}, calls, page=2)
        self.assertEqual(response.data['results'], [])
        self.assertEqual(response.data['total_pages'], 1)
        self.assertEqual(calls, [])

    def test_search_responses_are_cached(self):
        calls = []
        routes = {'/title/v2/find': {'results': []}}
        self.search('joker', routes, calls)
        self.search('joker', routes, calls)
        self.assertEqual(len(calls), 1)

    def test_invalid_page_is_400(self):
        response = self.client.get('/api/films/search', {'q': 'joker', 'page': 0})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'validation_error')

    def test_missing_key_returns_503(self):
        with override_settings(RAPIDAPI_KEY=''):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'movie_source_not_configured')

    def test_network_failure_returns_502(self):
        with mock.patch('films.movie_source.urlopen', side_effect=URLError('down')):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'movie_source_unavailable')

    def test_rejected_key_returns_502(self):
        error = HTTPError('https://rapidapi.com', 403, 'Forbidden', None, None)
        with mock.patch('films.movie_source.urlopen', side_effect=error):
            response = self.client.get('/api/films/search', {'q': 'joker'})
        self.assertEqual(response.status_code, 502)

    def test_detail_combines_overview_and_director(self):
        routes = {
            '/title/get-overview-details': SHAWSHANK_OVERVIEW,
            '/title/get-full-credits': SHAWSHANK_CREDITS,
        }
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['film_id'], 'tt0111161')
        self.assertEqual(response.data['title'], 'The Shawshank Redemption')
        self.assertEqual(response.data['runtime'], 142)
        self.assertEqual(response.data['genres'], ['Drama'])
        self.assertEqual(response.data['director'], 'Frank Darabont')
        self.assertEqual(response.data['rating'], 9.3)
        self.assertEqual(response.data['in_lists'], [])

    def test_detail_for_unknown_imdb_id_is_404(self):
        error = HTTPError('https://rapidapi.com', 404, 'Not Found', None, None)
        with mock.patch('films.movie_source.urlopen', side_effect=error):
            response = self.client.get('/api/films/tt9999999/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data['code'], 'film_not_found')

    def test_detail_without_title_payload_is_404(self):
        routes = {'/title/get-overview-details': {}, '/title/get-full-credits': {}}
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes)):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 404)

    def test_detail_upstream_failure_returns_502(self):
        with mock.patch('films.movie_source.urlopen', side_effect=TimeoutError()):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 502)

    def test_detail_missing_key_returns_503(self):
        with override_settings(RAPIDAPI_KEY=''):
            response = self.client.get('/api/films/tt0111161/')
        self.assertEqual(response.status_code, 503)

    def test_detail_responses_are_cached(self):
        calls = []
        routes = {
            '/title/get-overview-details': SHAWSHANK_OVERVIEW,
            '/title/get-full-credits': SHAWSHANK_CREDITS,
        }
        with mock.patch('films.movie_source.urlopen', side_effect=fake_upstream(routes, calls)):
            self.client.get('/api/films/tt0111161/')
            self.client.get('/api/films/tt0111161/')
        self.assertEqual(len(calls), 2)

    def test_detail_rejects_numeric_ids(self):
        response = self.client.get('/api/films/278/')
        self.assertEqual(response.status_code, 404)


class CatalogAuthTests(APITestCase):
    def test_catalog_requires_authentication(self):
        self.assertEqual(self.client.get('/api/films/search', {'q': 'joker'}).status_code, 401)
        self.assertEqual(self.client.get('/api/films/tt0111161/').status_code, 401)
