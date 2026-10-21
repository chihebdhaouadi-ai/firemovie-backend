from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import FilmReaction, Take, TakeComment, TakeVote

FILM = 'tt0111161'


class SummaryTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.cara = User.objects.create_user(username='cara', password='pw-123456')
        self.client.force_authenticate(self.viewer)

    def react(self, user, reaction):
        FilmReaction.objects.create(film_id=FILM, user=user, reaction=reaction)

    def summary(self):
        response = self.client.get(f'/api/takes/films/{FILM}/summary/')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_everyone_percent_counts_positive_over_positive_plus_negative(self):
        self.react(self.ana, 'loved')
        self.react(self.ben, 'bored')
        self.react(self.cara, 'shocked')
        data = self.summary()
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['everyone_percent'], 50)
        self.assertEqual(data['trusted_percent'], 50)

    def test_neutral_reactions_are_excluded_from_percentages(self):
        self.react(self.ana, 'shocked')
        self.react(self.ben, 'made_cry')
        data = self.summary()
        self.assertIsNone(data['everyone_percent'])
        self.assertIsNone(data['trusted_percent'])

    def test_most_felt_lists_top_three_with_counts(self):
        self.react(self.ana, 'loved')
        self.react(self.ben, 'loved')
        self.react(self.cara, 'bored')
        data = self.summary()
        self.assertEqual(
            data['most_felt'],
            [{'reaction': 'loved', 'count': 2}, {'reaction': 'bored', 'count': 1}],
        )

    def test_trusted_percent_weights_authors_with_well_argued_votes(self):
        take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Great.')
        for voter in (self.viewer, self.ben, self.cara):
            TakeVote.objects.create(take=take, user=voter, kind='well_argued')
        self.react(self.ana, 'loved')
        self.react(self.ben, 'bored')
        data = self.summary()
        self.assertEqual(data['everyone_percent'], 50)
        self.assertEqual(data['trusted_percent'], round(100 * 1.3 / 2.3))

    def test_my_reaction_reflects_viewer(self):
        self.react(self.viewer, 'masterpiece')
        self.assertEqual(self.summary()['my_reaction'], 'masterpiece')


class ReactionTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.client.force_authenticate(self.viewer)
        self.url = f'/api/takes/films/{FILM}/reaction/'

    def test_put_sets_reaction(self):
        response = self.client.put(self.url, {'reaction': 'loved'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['my_reaction'], 'loved')
        self.assertTrue(FilmReaction.objects.filter(user=self.viewer, reaction='loved').exists())

    def test_put_null_clears_reaction(self):
        self.client.put(self.url, {'reaction': 'loved'}, format='json')
        response = self.client.put(self.url, {'reaction': None}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['my_reaction'])
        self.assertFalse(FilmReaction.objects.filter(user=self.viewer).exists())

    def test_clearing_reaction_keeps_take_reaction(self):
        self.client.put(self.url, {'reaction': 'loved'}, format='json')
        self.client.post(f'/api/takes/films/{FILM}/takes/', {'body': 'Solid.'}, format='json')
        self.client.put(self.url, {'reaction': None}, format='json')
        self.assertEqual(Take.objects.get(film_id=FILM, author=self.viewer).reaction, 'loved')

    def test_changing_reaction_updates_existing_take(self):
        self.client.put(self.url, {'reaction': 'loved'}, format='json')
        self.client.post(f'/api/takes/films/{FILM}/takes/', {'body': 'Solid.'}, format='json')
        self.client.put(self.url, {'reaction': 'bored'}, format='json')
        self.assertEqual(Take.objects.get(film_id=FILM, author=self.viewer).reaction, 'bored')

    def test_invalid_reaction_is_rejected(self):
        response = self.client.put(self.url, {'reaction': 'meh'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_reaction')

    def test_missing_reaction_key_is_rejected(self):
        response = self.client.put(self.url, {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_reaction')


class TakeTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.url = f'/api/takes/films/{FILM}/takes/'

    def test_take_requires_reaction_first(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.url, {'body': 'Hi.'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'reaction_required')

    def test_take_is_created_with_reaction(self):
        FilmReaction.objects.create(film_id=FILM, user=self.viewer, reaction='made_think')
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.url, {'body': '  Hi.  '}, format='json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['body'], 'Hi.')
        self.assertEqual(data['reaction'], 'made_think')
        self.assertTrue(data['is_mine'])
        self.assertFalse(data['is_most_helpful'])

    def test_second_take_for_same_film_is_conflict(self):
        FilmReaction.objects.create(film_id=FILM, user=self.viewer, reaction='loved')
        self.client.force_authenticate(self.viewer)
        self.client.post(self.url, {'body': 'One.'}, format='json')
        response = self.client.post(self.url, {'body': 'Two.'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'already_posted')

    def test_empty_body_is_rejected(self):
        FilmReaction.objects.create(film_id=FILM, user=self.viewer, reaction='loved')
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.url, {'body': '   '}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_takes_are_ordered_by_helpfulness_and_flag_most_helpful_for_others(self):
        older = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Older.')
        Take.objects.create(film_id=FILM, author=self.ben, reaction='bored', body='Newer.')
        TakeVote.objects.create(take=older, user=self.ben, kind='well_argued')

        self.client.force_authenticate(self.viewer)
        takes = self.client.get(self.url).json()
        self.assertEqual([take['body'] for take in takes], ['Older.', 'Newer.'])
        self.assertTrue(takes[0]['is_most_helpful'])
        self.assertFalse(takes[1]['is_most_helpful'])

    def test_most_helpful_never_flags_own_take(self):
        mine = Take.objects.create(film_id=FILM, author=self.viewer, reaction='loved', body='Mine.')
        TakeVote.objects.create(take=mine, user=self.ana, kind='well_argued')

        self.client.force_authenticate(self.viewer)
        takes = self.client.get(self.url).json()
        self.assertEqual(takes[0]['id'], mine.id)
        self.assertFalse(takes[0]['is_most_helpful'])
        self.assertTrue(takes[0]['is_mine'])


class VoteTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Yes.')
        self.client.force_authenticate(self.viewer)

    def url(self, kind, take_id=None):
        return f'/api/takes/takes/{take_id or self.take.id}/votes/{kind}/'

    def test_vote_is_idempotent_and_can_be_removed(self):
        self.client.put(self.url('well_argued'), {'active': True}, format='json')
        response = self.client.put(self.url('well_argued'), {'active': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TakeVote.objects.filter(take=self.take, user=self.viewer).count(), 1)
        self.assertEqual(response.json()['votes']['well_argued'], 1)
        self.assertEqual(response.json()['my_votes'], ['well_argued'])

        response = self.client.put(self.url('well_argued'), {'active': False}, format='json')
        self.assertEqual(response.json()['votes']['well_argued'], 0)
        self.assertEqual(response.json()['my_votes'], [])

    def test_cannot_vote_on_own_take(self):
        self.client.force_authenticate(self.ana)
        response = self.client.put(self.url('well_argued'), {'active': True}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'own_take')

    def test_unknown_vote_kind_is_rejected(self):
        response = self.client.put(self.url('thumbs_up'), {'active': True}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_vote')

    def test_missing_take_is_404(self):
        response = self.client.put(self.url('well_argued', take_id=999999), {'active': True}, format='json')
        self.assertEqual(response.status_code, 404)


class CommentTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.viewer = User.objects.create_user(username='viewer', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Yes.')
        self.url = f'/api/takes/takes/{self.take.id}/comments/'

    def test_writer_comment_is_flagged(self):
        self.client.force_authenticate(self.ana)
        response = self.client.post(self.url, {'body': 'Thanks all.'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['is_writer'])

    def test_other_viewer_comment_is_not_writer(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.url, {'body': 'Agreed.'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()['is_writer'])

    def test_comments_list_in_order_and_counted_on_take(self):
        self.client.force_authenticate(self.viewer)
        self.client.post(self.url, {'body': 'First.'}, format='json')
        self.client.post(self.url, {'body': 'Second.'}, format='json')
        comments = self.client.get(self.url).json()
        self.assertEqual([comment['body'] for comment in comments], ['First.', 'Second.'])
        takes = self.client.get(f'/api/takes/films/{FILM}/takes/').json()
        self.assertEqual(takes[0]['comment_count'], 2)

    def test_comment_is_bounded_to_300_characters(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.url, {'body': 'x' * 301}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(TakeComment.objects.count(), 0)

    def test_missing_take_is_404(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get('/api/takes/takes/999999/comments/')
        self.assertEqual(response.status_code, 404)
