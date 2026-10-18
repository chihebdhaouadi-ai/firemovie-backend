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

    def test_numeric_tmdb_id_is_accepted_in_path(self):
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
