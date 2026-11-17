from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from social.models import FriendRequest

from .models import Take, TakeComment

FILM = 'tt0111161'
URL = '/api/takes/friends/stories/'


def befriend(a, b, status=FriendRequest.Status.ACCEPTED):
    FriendRequest.objects.create(sender=a, receiver=b, status=status)


class FriendStoriesTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.stranger = User.objects.create_user(username='zed', password='pw-123456')
        befriend(self.me, self.ana)
        befriend(self.ben, self.me)
        self.client.force_authenticate(self.me)

    def test_groups_takes_and_comments_per_friend_newest_friend_first(self):
        review = Take.objects.create(film_id=FILM, author=self.ana, body='Loved it.')
        question = Take.objects.create(film_id=FILM, author=self.ana, tag='question', body='Why?')
        TakeComment.objects.create(take=review, author=self.ben, body='Same here.')

        data = self.client.get(URL).json()

        self.assertEqual([g['user']['username'] for g in data], ['ben', 'ana'])
        ana = data[1]
        # Items play in the order they were made.
        self.assertEqual([i['id'] for i in ana['items']], [review.id, question.id])
        self.assertEqual(ana['items'][1]['tag'], 'question')
        self.assertEqual(ana['items'][0]['film']['film_id'], FILM)
        ben = data[0]['items'][0]
        self.assertEqual(ben['kind'], 'comment')
        self.assertEqual(ben['take_id'], review.id)
        self.assertEqual(ben['body'], 'Same here.')

    def test_leaves_out_strangers_pending_friends_and_old_items(self):
        pending = get_user_model().objects.create_user(username='pat', password='pw-123456')
        befriend(pending, self.me, FriendRequest.Status.PENDING)
        Take.objects.create(film_id=FILM, author=self.stranger, body='Hidden.')
        Take.objects.create(film_id=FILM, author=pending, body='Hidden too.')
        old = Take.objects.create(film_id=FILM, author=self.ana, body='Old news.')
        Take.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))

        self.assertEqual(self.client.get(URL).json(), [])

    def test_no_friends_means_no_stories(self):
        self.client.force_authenticate(self.stranger)
        Take.objects.create(film_id=FILM, author=self.ana, body='Hi.')
        self.assertEqual(self.client.get(URL).json(), [])

    def test_needs_an_account(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL).status_code, (401, 403))
