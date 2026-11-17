from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from social.models import FriendRequest

from .models import Conversation, Message

BASE = '/api/messaging/conversations/'


def befriend(a, b):
    FriendRequest.objects.create(sender=a, receiver=b, status=FriendRequest.Status.ACCEPTED)


class MessagingTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.zed = User.objects.create_user(username='zed', password='pw-123456')
        befriend(self.me, self.ana)
        befriend(self.ben, self.me)
        self.client.force_authenticate(self.me)

    def open_direct(self, user):
        return self.client.post(BASE, {'kind': 'direct', 'user_id': user.id}, format='json')

    def test_direct_chat_is_created_once_and_titled_after_the_friend(self):
        first = self.open_direct(self.ana)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['title'], 'ana')
        again = self.open_direct(self.ana)
        self.assertEqual(again.json()['id'], first.json()['id'])
        # Ana sees the same chat, titled after me.
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.get(BASE).json()[0]['title'], 'me')

    def test_only_friends_can_be_messaged_or_added(self):
        response = self.open_direct(self.zed)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'not_friends')
        response = self.client.post(
            BASE,
            {'kind': 'group', 'title': 'Club', 'member_ids': [self.ana.id, self.zed.id]},
            format='json',
        )
        self.assertEqual(response.json()['code'], 'not_friends')
        self.assertFalse(Conversation.objects.filter(kind='group').exists())

    def test_group_and_topic_need_a_name(self):
        response = self.client.post(BASE, {'kind': 'topic', 'title': ' '}, format='json')
        self.assertEqual(response.json()['code'], 'title_required')
        response = self.client.post(
            BASE,
            {'kind': 'topic', 'title': 'Noir night', 'member_ids': [self.ana.id, self.ben.id]},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['kind'], 'topic')
        self.assertEqual(data['title'], 'Noir night')
        self.assertEqual(
            sorted(m['username'] for m in data['members']), ['ana', 'ben', 'me']
        )

    def test_messages_flow_with_unread_counts(self):
        convo = self.open_direct(self.ana).json()['id']
        url = f'{BASE}{convo}/messages/'
        sent = self.client.post(url, {'body': ' Seen Heat yet? '}, format='json')
        self.assertEqual(sent.status_code, 201)
        self.assertEqual(sent.json()['body'], 'Seen Heat yet?')

        # Ana has one unread message until she opens the chat.
        self.client.force_authenticate(self.ana)
        row = self.client.get(BASE).json()[0]
        self.assertEqual(row['unread'], 1)
        self.assertEqual(row['last_message']['body'], 'Seen Heat yet?')
        messages = self.client.get(url).json()
        self.assertEqual([m['body'] for m in messages], ['Seen Heat yet?'])
        self.assertEqual(self.client.get(BASE).json()[0]['unread'], 0)

        reply = self.client.post(url, {'body': 'Best heist ever'}, format='json').json()
        self.client.force_authenticate(self.me)
        newer = self.client.get(url, {'after': sent.json()['id']}).json()
        self.assertEqual([m['id'] for m in newer], [reply['id']])

    def test_newest_conversation_comes_first(self):
        with_ana = self.open_direct(self.ana).json()['id']
        with_ben = self.open_direct(self.ben).json()['id']
        self.client.post(f'{BASE}{with_ana}/messages/', {'body': 'hi'}, format='json')
        ids = [row['id'] for row in self.client.get(BASE).json()]
        self.assertEqual(ids, [with_ana, with_ben])

    def test_outsiders_cannot_read_or_post(self):
        convo = self.open_direct(self.ana).json()['id']
        self.client.force_authenticate(self.zed)
        self.assertEqual(self.client.get(f'{BASE}{convo}/messages/').status_code, 404)
        response = self.client.post(f'{BASE}{convo}/messages/', {'body': 'hey'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Message.objects.count(), 0)

    def test_empty_message_is_refused(self):
        convo = self.open_direct(self.ana).json()['id']
        response = self.client.post(f'{BASE}{convo}/messages/', {'body': '  '}, format='json')
        self.assertEqual(response.json()['code'], 'empty_message')
