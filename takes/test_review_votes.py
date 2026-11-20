from importlib import import_module

from django.apps import apps
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from .models import Take, TakeComment, TakeVote
from .reputation import progress_for

FILM = 'tt0111161'


class ReviewVoteTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.review = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Wow.')
        self.client.force_authenticate(self.ben)

    def put(self, kind, take=None, active=True):
        take = take or self.review
        return self.client.put(f'/api/takes/takes/{take.id}/votes/{kind}/', {'active': active}, format='json')

    def test_a_reader_has_one_of_up_draw_or_down(self):
        self.put('up')
        response = self.put('down')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['votes']['up'], 0)
        self.assertEqual(data['votes']['down'], 1)
        self.assertEqual(data['my_votes'], ['down'])

        data = self.put('down', active=False).json()
        self.assertEqual(data['my_votes'], [])
        self.assertEqual(data['votes']['draw'], 0)

    def test_old_kinds_and_review_kinds_on_topics_are_refused(self):
        self.assertEqual(self.put('well_argued').status_code, 400)
        topic = Take.objects.create(film_id='', author=self.ana, tag='question', body='Why?')
        self.assertEqual(self.put('up', take=topic).status_code, 400)

    def test_changed_my_mind_comments_earn_their_badge(self):
        self.client.post(
            f'/api/takes/takes/{self.review.id}/comments/',
            {'body': 'You convinced me', 'stance': 'changed_my_mind'},
            format='json',
        )
        self.assertEqual(TakeVote.objects.get().kind, 'up')
        badges = {b['key']: b['current'] for b in progress_for(self.ana)['badges']}
        self.assertEqual(badges['changed_my_mind'], 1)
        self.assertEqual(badges['well_argued'], 1)


class LegacyVoteMigrationTests(APITestCase):
    def test_old_votes_become_one_up_or_draw_per_reader(self):
        User = get_user_model()
        ana = User.objects.create_user(username='ana', password='pw-123456')
        ben = User.objects.create_user(username='ben', password='pw-123456')
        cara = User.objects.create_user(username='cara', password='pw-123456')
        take = Take.objects.create(film_id=FILM, author=ana, reaction='loved', body='Wow.')
        TakeVote.objects.create(take=take, user=ben, kind='well_argued')
        TakeVote.objects.create(take=take, user=ben, kind='disagree_but_fair')
        TakeVote.objects.create(take=take, user=cara, kind='disagree_but_fair')

        migration = import_module('takes.migrations.0013_review_votes_up_draw_down')
        migration.to_up_draw_down(apps, None)

        kinds = dict(TakeVote.objects.values_list('user__username', 'kind'))
        self.assertEqual(kinds, {'ben': 'up', 'cara': 'draw'})
        self.assertFalse(TakeComment.objects.exists())
