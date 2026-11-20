"""End-to-end walk through every way a notification is made, read and
cleared, through the real API, the way the app calls it."""

from rest_framework.test import APITestCase

from accounts.models import User
from takes.models import Take

FILM = 'tt0137523'
NOTIFICATIONS = '/api/social/notifications'


class NotificationFlowTests(APITestCase):
    def setUp(self):
        self.ana = User.objects.create_user(username='ana', email='ana@example.com', password='pw-12345')
        self.ben = User.objects.create_user(username='ben', email='ben@example.com', password='pw-12345')
        self.cat = User.objects.create_user(username='cat', email='cat@example.com', password='pw-12345')

    def as_(self, user):
        self.client.force_authenticate(user)
        return self.client

    def inbox(self, user):
        data = self.as_(user).get(NOTIFICATIONS).data
        return data['unread_count'], data['results']

    def befriend(self, sender, receiver):
        self.as_(sender).post('/api/social/friend-requests', {'user_id': receiver.id}, format='json')
        request_id = self.inbox(receiver)[1][0]['friend_request_id']
        self.as_(receiver).post(f'/api/social/friend-requests/{request_id}/accept')

    def test_friend_request_then_accept(self):
        sent = self.as_(self.ana).post('/api/social/friend-requests', {'user_id': self.ben.id}, format='json')
        self.assertEqual(sent.status_code, 201)

        unread, items = self.inbox(self.ben)
        self.assertEqual(unread, 1)
        self.assertEqual(items[0]['kind'], 'friend_request')
        self.assertEqual(items[0]['actor']['username'], 'ana')
        self.assertIsNotNone(items[0]['created_at'])
        request_id = items[0]['friend_request_id']

        accepted = self.as_(self.ben).post(f'/api/social/friend-requests/{request_id}/accept')
        self.assertEqual(accepted.status_code, 200)

        # Ana hears back.
        unread, items = self.inbox(self.ana)
        self.assertEqual((unread, items[0]['kind'], items[0]['actor']['username']),
                         (1, 'friend_accepted', 'ben'))

        # Ben's request row no longer offers Accept: the request is answered.
        _, items = self.inbox(self.ben)
        self.assertEqual(items[0]['kind'], 'friend_request')
        self.assertIsNone(items[0]['friend_request_id'])

    def test_declining_removes_the_request_notification(self):
        self.as_(self.ana).post('/api/social/friend-requests', {'user_id': self.ben.id}, format='json')
        request_id = self.inbox(self.ben)[1][0]['friend_request_id']

        declined = self.as_(self.ben).post(f'/api/social/friend-requests/{request_id}/decline')
        self.assertEqual(declined.status_code, 204)
        self.assertEqual(self.inbox(self.ben), (0, []))
        # Ana is not told.
        self.assertEqual(self.inbox(self.ana), (0, []))

    def test_cancelling_a_sent_request_removes_it_from_their_inbox(self):
        self.as_(self.ana).post('/api/social/friend-requests', {'user_id': self.ben.id}, format='json')
        request_id = self.inbox(self.ben)[1][0]['friend_request_id']

        cancelled = self.as_(self.ana).post(f'/api/social/friend-requests/{request_id}/cancel')
        self.assertEqual(cancelled.status_code, 204)
        self.assertEqual(self.inbox(self.ben), (0, []))

    def test_movie_suggestion(self):
        self.befriend(self.ana, self.ben)
        sent = self.as_(self.ana).post('/api/social/movie-suggestions', {
            'film_id': '603', 'film_title': 'The Matrix', 'film_year': 1999,
            'film_poster_url': '', 'comment': 'Watch it', 'recipient_ids': [self.ben.id],
        }, format='json')
        self.assertEqual(sent.status_code, 201)

        _, items = self.inbox(self.ben)
        latest = items[0]
        self.assertEqual(latest['kind'], 'movie_suggestion')
        self.assertEqual(latest['suggestion']['film_title'], 'The Matrix')
        self.assertEqual(latest['suggestion']['comment'], 'Watch it')

    def test_take_share_and_mention(self):
        self.befriend(self.ana, self.ben)
        topic = Take.objects.create(film_id=FILM, author=self.ana, tag='question', body='Are we free?')

        shared = self.as_(self.ana).post(
            f'/api/takes/takes/{topic.id}/share/',
            {'recipient_ids': [self.ben.id], 'message': 'koi'}, format='json',
        )
        self.assertEqual(shared.status_code, 201)
        _, items = self.inbox(self.ben)
        share = items[0]
        self.assertEqual((share['kind'], share['message']), ('take_shared', 'koi'))
        self.assertEqual(share['take']['id'], topic.id)
        self.assertEqual(share['take']['body'], 'Are we free?')

        # Tagging a friend notifies them with the comment to open; tagging a
        # stranger or yourself does not.
        posted = self.as_(self.ana).post(
            f'/api/takes/takes/{topic.id}/comments/',
            {'body': '@ben what do you think? @cat @ana'}, format='json',
        )
        self.assertEqual(posted.status_code, 201)
        _, items = self.inbox(self.ben)
        mention = items[0]
        self.assertEqual(mention['kind'], 'take_mention')
        self.assertEqual(mention['comment_id'], posted.data['id'])
        self.assertEqual(self.inbox(self.cat), (0, []))
        self.assertFalse(any(n['kind'] == 'take_mention' for n in self.inbox(self.ana)[1]))

    def test_marking_read_one_then_all(self):
        self.befriend(self.ana, self.ben)
        topic = Take.objects.create(film_id=FILM, author=self.ana, tag='question', body='Q')
        self.as_(self.ana).post(f'/api/takes/takes/{topic.id}/share/', {'recipient_ids': [self.ben.id]}, format='json')
        self.as_(self.ana).post(f'/api/takes/takes/{topic.id}/comments/', {'body': '@ben hi'}, format='json')

        unread, items = self.inbox(self.ben)
        # The request Ben accepted, the share and the mention.
        self.assertEqual(unread, 3)

        one = self.as_(self.ben).post(f'{NOTIFICATIONS}/{items[0]["id"]}/read')
        self.assertEqual(one.status_code, 204)
        self.assertEqual(self.inbox(self.ben)[0], 2)

        # Ana can't mark Ben's notifications.
        self.assertEqual(self.as_(self.ana).post(f'{NOTIFICATIONS}/{items[1]["id"]}/read').status_code, 404)

        self.as_(self.ben).post(f'{NOTIFICATIONS}/read')
        unread, items = self.inbox(self.ben)
        self.assertEqual(unread, 0)
        self.assertTrue(all(n['read'] for n in items))

    def test_newest_first_and_deleting_the_take_clears_its_notifications(self):
        self.befriend(self.ana, self.ben)
        topic = Take.objects.create(film_id=FILM, author=self.ana, tag='question', body='Q')
        self.as_(self.ana).post(f'/api/takes/takes/{topic.id}/share/', {'recipient_ids': [self.ben.id]}, format='json')

        kinds = [n['kind'] for n in self.inbox(self.ben)[1]]
        self.assertEqual(kinds, ['take_shared', 'friend_request'])

        topic.delete()
        kinds = [n['kind'] for n in self.inbox(self.ben)[1]]
        self.assertEqual(kinds, ['friend_request'])

    def test_notifications_need_a_signed_in_user(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(NOTIFICATIONS).status_code, (401, 403))
