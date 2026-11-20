from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from social.models import FriendRequest, Notification

from .models import FilmReaction, Take, TakeReport

FILM = 'tt0111161'


def befriend(a, b):
    FriendRequest.objects.create(sender=a, receiver=b, status=FriendRequest.Status.ACCEPTED)


class TakeOwnerTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='First.')
        self.url = f'/api/takes/takes/{self.take.id}/'

    def test_detail_returns_the_take_with_its_film(self):
        self.client.force_authenticate(self.ben)
        data = self.client.get(self.url).json()
        self.assertEqual(data['id'], self.take.id)
        self.assertEqual(data['film']['film_id'], FILM)
        self.assertFalse(data['edited'])

    def test_author_can_edit_body_and_skin(self):
        self.client.force_authenticate(self.ana)
        response = self.client.patch(
            self.url, {'body': ' Second. ', 'skin': 'electric_thunder'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['body'], 'Second.')
        self.assertEqual(data['skin'], 'electric_thunder')
        self.assertTrue(data['edited'])
        self.take.refresh_from_db()
        self.assertIsNotNone(self.take.edited_at)

    def test_others_cannot_edit_or_delete(self):
        self.client.force_authenticate(self.ben)
        response = self.client.patch(self.url, {'body': 'Mine now.'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'not_owner')
        self.assertEqual(self.client.delete(self.url).status_code, 403)
        self.take.refresh_from_db()
        self.assertEqual(self.take.body, 'First.')

    def test_topics_keep_their_shorter_limit(self):
        topic = Take.objects.create(film_id=FILM, author=self.ana, tag='question', body='Why?')
        self.client.force_authenticate(self.ana)
        response = self.client.patch(
            f'/api/takes/takes/{topic.id}/', {'body': 'x' * 281}, format='json'
        )
        self.assertEqual(response.status_code, 400)

    def test_author_can_delete(self):
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertFalse(Take.objects.filter(id=self.take.id).exists())


class TakeReportTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Rude.')
        self.url = f'/api/takes/takes/{self.take.id}/report/'

    def test_report_is_saved_once_per_viewer(self):
        self.client.force_authenticate(self.ben)
        first = self.client.post(self.url, {'reason': 'spam'}, format='json')
        again = self.client.post(
            self.url, {'reason': 'harassment', 'details': 'Insults me'}, format='json'
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(again.status_code, 200)
        report = TakeReport.objects.get()
        self.assertEqual(report.reason, 'harassment')
        self.assertEqual(report.details, 'Insults me')

    def test_own_take_cannot_be_reported(self):
        self.client.force_authenticate(self.ana)
        response = self.client.post(self.url, {'reason': 'spam'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'own_take')

    def test_unknown_reason_is_rejected(self):
        self.client.force_authenticate(self.ben)
        response = self.client.post(self.url, {'reason': 'boring'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TakeReport.objects.exists())


class TakeShareTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.cara = User.objects.create_user(username='cara', password='pw-123456')
        befriend(self.ana, self.ben)
        self.take = Take.objects.create(film_id=FILM, author=self.cara, reaction='loved', body='Wow.')
        self.url = f'/api/takes/takes/{self.take.id}/share/'

    def test_sharing_notifies_friends_with_a_link_to_the_take(self):
        self.client.force_authenticate(self.ana)
        response = self.client.post(
            self.url, {'recipient_ids': [self.ben.id], 'message': 'Read this'}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['sent'], 1)

        self.client.force_authenticate(self.ben)
        item = self.client.get('/api/social/notifications').json()['results'][0]
        self.assertEqual(item['kind'], 'take_shared')
        self.assertEqual(item['actor']['username'], 'ana')
        self.assertEqual(item['message'], 'Read this')
        self.assertEqual(item['take']['id'], self.take.id)
        self.assertEqual(item['take']['film_id'], FILM)
        self.assertEqual(item['take']['tag'], 'review')

    def test_sharing_with_a_non_friend_is_refused(self):
        self.client.force_authenticate(self.ana)
        response = self.client.post(self.url, {'recipient_ids': [self.cara.id]}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'not_friends')
        self.assertFalse(Notification.objects.exists())


class MentionTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='Ben.K', password='pw-123456')
        self.cara = User.objects.create_user(username='cara', password='pw-123456')
        befriend(self.ana, self.ben)
        self.take = Take.objects.create(film_id=FILM, author=self.cara, reaction='loved', body='Wow.')
        self.url = f'/api/takes/takes/{self.take.id}/comments/'

    def test_tagged_friends_are_notified_with_the_comment(self):
        self.client.force_authenticate(self.ana)
        response = self.client.post(
            self.url, {'body': 'What do you think @ben.k? cc @cara'}, format='json'
        )
        self.assertEqual(response.status_code, 201)

        mention = Notification.objects.get()
        self.assertEqual(mention.recipient, self.ben)
        self.assertEqual(mention.kind, 'take_mention')
        self.assertEqual(mention.take, self.take)
        self.assertEqual(mention.comment_id, response.json()['id'])

    def test_emails_and_self_mentions_do_not_notify(self):
        self.client.force_authenticate(self.ana)
        self.client.post(self.url, {'body': 'mail ben.k@x.com, me @ana'}, format='json')
        self.assertFalse(Notification.objects.exists())

    def test_a_friend_tagged_twice_gets_one_notification(self):
        self.client.force_authenticate(self.ana)
        self.client.post(self.url, {'body': '@Ben.K @ben.k.'}, format='json')
        self.assertEqual(Notification.objects.count(), 1)


class ChatCardTests(APITestCase):
    """Shares and mentions also land in the direct chat as a take card."""

    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        self.cara = User.objects.create_user(username='cara', password='pw-123456')
        befriend(self.ana, self.ben)
        self.topic = Take.objects.create(
            film_id=FILM, author=self.cara, tag='question', title='Free?', body='Are we?'
        )

    def _ben_chat_messages(self):
        self.client.force_authenticate(self.ben)
        rows = self.client.get('/api/messaging/conversations/').json()
        rows = rows['results'] if isinstance(rows, dict) else rows
        self.assertEqual(len(rows), 1)
        convo = rows[0]
        data = self.client.get(f"/api/messaging/conversations/{convo['id']}/messages/").json()
        return convo, data['results'] if isinstance(data, dict) else data

    def test_a_shared_topic_shows_up_in_the_chat_as_a_card(self):
        self.client.force_authenticate(self.ana)
        self.client.post(
            f'/api/takes/takes/{self.topic.id}/share/',
            {'recipient_ids': [self.ben.id], 'message': 'Look'},
            format='json',
        )
        convo, messages = self._ben_chat_messages()
        card = messages[-1]
        self.assertEqual(card['kind'], 'take')
        self.assertEqual(card['body'], 'Look')
        self.assertEqual(card['sender']['username'], 'ana')
        self.assertEqual(card['payload']['event'], 'shared')
        self.assertEqual(card['payload']['take']['id'], self.topic.id)
        self.assertEqual(card['payload']['take']['title'], 'Free?')
        self.assertNotIn('comment', card['payload'])
        self.assertEqual(convo['last_message']['kind'], 'take')

    def test_a_mention_in_a_reply_links_to_that_exact_comment(self):
        self.client.force_authenticate(self.ana)
        first = self.client.post(
            f'/api/takes/takes/{self.topic.id}/comments/', {'body': 'Yes'}, format='json'
        ).json()
        reply = self.client.post(
            f'/api/takes/takes/{self.topic.id}/comments/',
            {'body': 'Agree @ben?', 'parent_id': first['id']},
            format='json',
        ).json()
        _, messages = self._ben_chat_messages()
        card = messages[-1]
        self.assertEqual(card['payload']['event'], 'mention')
        self.assertEqual(card['payload']['take']['id'], self.topic.id)
        self.assertEqual(card['payload']['comment']['id'], reply['id'])
        self.assertEqual(card['payload']['comment']['body'], 'Agree @ben?')

    def test_no_card_when_blocked(self):
        from messaging.models import Block, Message

        Block.objects.create(blocker=self.ben, blocked=self.ana)
        self.client.force_authenticate(self.ana)
        self.client.post(
            f'/api/takes/takes/{self.topic.id}/share/', {'recipient_ids': [self.ben.id]}, format='json'
        )
        self.assertFalse(Message.objects.filter(kind='take').exists())

    def test_take_cards_cannot_be_posted_by_hand(self):
        from messaging.services import open_direct

        convo = open_direct(self.ana, self.ben.id)
        self.client.force_authenticate(self.ana)
        response = self.client.post(
            f'/api/messaging/conversations/{convo.id}/messages/',
            {'kind': 'take', 'body': 'x'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)


class SpoilerTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        FilmReaction.objects.create(film_id=FILM, user=self.ana, reaction='loved')
        self.client.force_authenticate(self.ana)

    def test_a_review_can_be_marked_as_a_spoiler(self):
        response = self.client.post(
            f'/api/takes/films/{FILM}/takes/', {'body': 'The twist!', 'spoiler': True}, format='json'
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['spoiler'])
        self.assertTrue(Take.objects.get().spoiler)

    def test_reviews_are_not_spoilers_unless_marked(self):
        response = self.client.post(f'/api/takes/films/{FILM}/takes/', {'body': 'Calm.'}, format='json')
        self.assertFalse(response.json()['spoiler'])

    def test_the_author_can_change_the_spoiler_flag(self):
        take = Take.objects.create(film_id=FILM, author=self.ana, reaction='loved', body='Ends well.')
        response = self.client.patch(
            f'/api/takes/takes/{take.id}/', {'body': 'Ends well.', 'spoiler': True}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['spoiler'])
        # Leaving it out keeps it.
        self.client.patch(f'/api/takes/takes/{take.id}/', {'body': 'Ends.'}, format='json')
        take.refresh_from_db()
        self.assertTrue(take.spoiler)
