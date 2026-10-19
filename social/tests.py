from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User

from .models import FriendRequest, Follow, MovieSuggestion, Notification


class SocialTestBase(APITestCase):
    def setUp(self):
        self.me = User.objects.create_user(username='alice', email='a@example.com', password='pw-12345')
        self.other = User.objects.create_user(username='albert', email='b@example.com', password='pw-12345')
        self.stranger = User.objects.create_user(username='bob', email='c@example.com', password='pw-12345')


class UserSearchTests(SocialTestBase):
    def test_short_query_returns_empty_list(self):
        self.client.force_authenticate(self.me)
        response = self.client.get('/api/social/users/search', {'q': 'a'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_search_matches_username_and_excludes_self(self):
        self.client.force_authenticate(self.me)
        response = self.client.get('/api/social/users/search', {'q': 'AL'})
        self.assertEqual([u['username'] for u in response.data], ['albert'])
        self.assertEqual(set(response.data[0]), {'id', 'username', 'avatar'})


class FriendRequestTests(SocialTestBase):
    def send(self, sender, receiver):
        self.client.force_authenticate(sender)
        return self.client.post('/api/social/friend-requests', {'user_id': receiver.id}, format='json')

    def test_send_creates_request_follow_and_notification(self):
        response = self.send(self.me, self.other)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending')
        self.assertTrue(FriendRequest.objects.filter(sender=self.me, receiver=self.other).exists())
        self.assertTrue(Follow.objects.filter(follower=self.me, following=self.other).exists())
        notification = Notification.objects.get(recipient=self.other)
        self.assertEqual(notification.kind, Notification.Kind.FRIEND_REQUEST)
        self.assertEqual(notification.actor, self.me)

    def test_sending_to_self_is_rejected(self):
        response = self.send(self.me, self.me)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)

    def test_duplicate_request_is_rejected_in_either_direction(self):
        self.send(self.me, self.other)
        self.assertEqual(self.send(self.me, self.other).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.send(self.other, self.me).status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_user_returns_404(self):
        self.client.force_authenticate(self.me)
        response = self.client.post('/api/social/friend-requests', {'user_id': 999999}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_accept_by_receiver_creates_reverse_follow_and_notifies_sender(self):
        self.send(self.me, self.other)
        request_id = FriendRequest.objects.get().id

        self.client.force_authenticate(self.other)
        response = self.client.post(f'/api/social/friend-requests/{request_id}/accept')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'status': 'accepted'})
        self.assertTrue(Follow.objects.filter(follower=self.other, following=self.me).exists())
        notification = Notification.objects.get(recipient=self.me, kind=Notification.Kind.FRIEND_ACCEPTED)
        self.assertEqual(notification.actor, self.other)

    def test_accept_by_sender_is_not_found(self):
        self.send(self.me, self.other)
        request_id = FriendRequest.objects.get().id

        self.client.force_authenticate(self.me)
        response = self.client.post(f'/api/social/friend-requests/{request_id}/accept')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_decline_removes_request_and_follow(self):
        self.send(self.me, self.other)
        request_id = FriendRequest.objects.get().id

        self.client.force_authenticate(self.other)
        response = self.client.post(f'/api/social/friend-requests/{request_id}/decline')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FriendRequest.objects.exists())
        self.assertFalse(Follow.objects.filter(follower=self.me, following=self.other).exists())

    def test_cancel_by_sender_removes_request(self):
        self.send(self.me, self.other)
        request_id = FriendRequest.objects.get().id

        self.client.force_authenticate(self.me)
        response = self.client.post(f'/api/social/friend-requests/{request_id}/cancel')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(FriendRequest.objects.exists())

    def test_cancel_by_receiver_is_not_found(self):
        self.send(self.me, self.other)
        request_id = FriendRequest.objects.get().id

        self.client.force_authenticate(self.other)
        response = self.client.post(f'/api/social/friend-requests/{request_id}/cancel')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class FriendshipOnProfileTests(SocialTestBase):
    def profile_seen_by(self, viewer, target):
        self.client.force_authenticate(viewer)
        response = self.client.get(f'/api/account/users/{target.id}')
        return response.data

    def test_friendship_states(self):
        self.assertEqual(self.profile_seen_by(self.other, self.other)['friendship'], 'self')
        self.assertEqual(self.profile_seen_by(self.me, self.other)['friendship'], 'none')

        self.client.force_authenticate(self.me)
        self.client.post('/api/social/friend-requests', {'user_id': self.other.id}, format='json')
        self.assertEqual(self.profile_seen_by(self.me, self.other)['friendship'], 'outgoing')

        data = self.profile_seen_by(self.other, self.me)
        self.assertEqual(data['friendship'], 'incoming')
        self.assertIsNotNone(data['friend_request_id'])
        self.assertNotIn('email', data)

        request_id = FriendRequest.objects.get().id
        self.client.force_authenticate(self.other)
        self.client.post(f'/api/social/friend-requests/{request_id}/accept')
        data = self.profile_seen_by(self.me, self.other)
        self.assertEqual(data['friendship'], 'friends')
        self.assertIsNone(data['friend_request_id'])
        self.assertEqual(data['followers'], 1)
        self.assertEqual(data['following'], 1)


class ConnectionsAndNotificationsTests(SocialTestBase):
    def test_connections_list_following_and_followers(self):
        Follow.objects.create(follower=self.me, following=self.other)
        Follow.objects.create(follower=self.stranger, following=self.me)

        self.client.force_authenticate(self.me)
        response = self.client.get('/api/social/me/connections')

        self.assertEqual([u['username'] for u in response.data['following']], ['albert'])
        self.assertEqual([u['username'] for u in response.data['followers']], ['bob'])

    def test_notifications_report_unread_and_mark_read(self):
        self.client.force_authenticate(self.me)
        self.client.post('/api/social/friend-requests', {'user_id': self.other.id}, format='json')

        self.client.force_authenticate(self.other)
        response = self.client.get('/api/social/notifications')
        self.assertEqual(response.data['unread_count'], 1)
        self.assertEqual(response.data['results'][0]['kind'], 'friend_request')
        self.assertIsNotNone(response.data['results'][0]['friend_request_id'])

        response = self.client.post('/api/social/notifications/read')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        response = self.client.get('/api/social/notifications')
        self.assertEqual(response.data['unread_count'], 0)


class MovieSuggestionTests(SocialTestBase):
    SUGGESTION = {
        'film_id': '603',
        'film_title': 'The Matrix',
        'film_year': 1999,
        'film_poster_url': 'https://img.test/matrix.jpg',
        'comment': '  Great pick  ',
    }

    def setUp(self):
        super().setUp()
        self.carol = User.objects.create_user(username='carol', email='d@example.com', password='pw-12345')
        FriendRequest.objects.create(
            sender=self.me, receiver=self.other, status=FriendRequest.Status.ACCEPTED,
        )
        FriendRequest.objects.create(
            sender=self.carol, receiver=self.me, status=FriendRequest.Status.ACCEPTED,
        )

    def send(self, sender, recipient_ids, **overrides):
        self.client.force_authenticate(sender)
        body = {**self.SUGGESTION, 'recipient_ids': recipient_ids, **overrides}
        return self.client.post('/api/social/movie-suggestions', body, format='json')

    def test_send_to_friends_creates_suggestions_and_notifications(self):
        response = self.send(self.me, [self.other.id, self.carol.id])

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data, {'sent': 2})
        self.assertEqual(MovieSuggestion.objects.count(), 2)
        suggestion = MovieSuggestion.objects.get(recipient=self.carol)
        self.assertEqual(suggestion.sender, self.me)
        self.assertEqual(suggestion.film_title, 'The Matrix')
        self.assertEqual(suggestion.comment, 'Great pick')
        notifications = Notification.objects.filter(kind=Notification.Kind.MOVIE_SUGGESTION)
        self.assertEqual(notifications.count(), 2)
        self.assertEqual(
            set(notifications.values_list('recipient_id', flat=True)),
            {self.other.id, self.carol.id},
        )
        self.assertTrue(all(n.actor == self.me and n.suggestion for n in notifications))

    def test_non_friend_recipient_is_rejected_and_nothing_is_created(self):
        response = self.send(self.me, [self.other.id, self.stranger.id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'not_friends')
        self.assertFalse(MovieSuggestion.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_sending_to_self_is_rejected(self):
        response = self.send(self.me, [self.me.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'not_friends')

    def test_unknown_recipient_is_rejected(self):
        response = self.send(self.me, [self.other.id, 999999])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'not_friends')
        self.assertFalse(MovieSuggestion.objects.exists())

    def test_empty_recipient_list_is_rejected(self):
        response = self.send(self.me, [])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_recipients_are_rejected(self):
        response = self.send(self.me, [self.other.id, self.other.id])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(MovieSuggestion.objects.exists())

    def test_comment_over_limit_is_rejected(self):
        response = self.send(self.me, [self.other.id], comment='x' * 281)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(MovieSuggestion.objects.exists())

    def test_anonymous_request_is_rejected(self):
        response = self.client.post(
            '/api/social/movie-suggestions',
            {**self.SUGGESTION, 'recipient_ids': [self.other.id]},
            format='json',
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertFalse(MovieSuggestion.objects.exists())

    def test_friends_are_listed_in_both_directions(self):
        self.client.force_authenticate(self.me)
        response = self.client.get('/api/social/me/connections')
        self.assertEqual([u['username'] for u in response.data['friends']], ['albert', 'carol'])

    def test_pending_requests_are_not_listed_as_friends(self):
        self.client.force_authenticate(self.stranger)
        self.client.post('/api/social/friend-requests', {'user_id': self.me.id}, format='json')

        self.client.force_authenticate(self.me)
        response = self.client.get('/api/social/me/connections')
        self.assertNotIn('bob', [u['username'] for u in response.data['friends']])

    def test_notifications_expose_suggestion_payload(self):
        self.send(self.me, [self.other.id])
        self.client.force_authenticate(self.stranger)
        self.client.post('/api/social/friend-requests', {'user_id': self.other.id}, format='json')

        self.client.force_authenticate(self.other)
        response = self.client.get('/api/social/notifications')
        by_kind = {item['kind']: item for item in response.data['results']}

        self.assertEqual(by_kind['movie_suggestion']['suggestion'], {
            'film_id': '603',
            'film_title': 'The Matrix',
            'film_year': 1999,
            'film_poster_url': 'https://img.test/matrix.jpg',
            'comment': 'Great pick',
        })
        self.assertIsNone(by_kind['friend_request']['suggestion'])
