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


# A 1x1 PNG.
PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082'
)


class GroupDetailsTests(APITestCase):
    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media.enable()
        self.addCleanup(self._media.disable)
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.zed = User.objects.create_user(username='zed', password='pw-123456')
        befriend(self.me, self.ana)
        self.client.force_authenticate(self.me)

    def create_group(self, **extra):
        body = {'kind': 'group', 'title': 'Heist club', 'member_ids': [self.ana.id], **extra}
        return self.client.post(BASE, body, format='json')

    def test_group_is_created_with_a_description(self):
        row = self.create_group(description='  Only heist films.  ').json()
        self.assertEqual(row['description'], 'Only heist films.')
        self.assertIsNone(row['photo'])
        self.assertEqual(row['created_by'], self.me.id)
        detail = self.client.get(f"{BASE}{row['id']}/").json()
        self.assertEqual(detail['description'], 'Only heist films.')
        self.assertEqual({m['username'] for m in detail['members']}, {'me', 'ana'})

    def test_too_long_description_is_refused(self):
        response = self.create_group(description='x' * 301)
        self.assertEqual(response.json()['code'], 'description_too_long')
        self.assertEqual(Conversation.objects.count(), 0)

    def test_member_uploads_a_group_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        convo = self.create_group().json()['id']
        photo = SimpleUploadedFile('group.png', PNG, content_type='image/png')
        response = self.client.patch(f'{BASE}{convo}/', {'photo': photo}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['photo'].startswith('http'))
        self.assertIn('conversation_photos/', response.json()['photo'])

    def test_photo_must_be_an_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        convo = self.create_group().json()['id']
        bad = SimpleUploadedFile('group.png', b'not an image', content_type='image/png')
        response = self.client.patch(f'{BASE}{convo}/', {'photo': bad}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_direct_chats_cannot_be_renamed(self):
        convo = self.client.post(BASE, {'kind': 'direct', 'user_id': self.ana.id}, format='json').json()['id']
        response = self.client.patch(f'{BASE}{convo}/', {'title': 'x'}, format='json')
        self.assertEqual(response.json()['code'], 'direct_chat')

    def test_outsiders_cannot_see_or_change_a_group(self):
        convo = self.create_group().json()['id']
        self.client.force_authenticate(self.zed)
        self.assertEqual(self.client.get(f'{BASE}{convo}/').status_code, 404)
        response = self.client.patch(f'{BASE}{convo}/', {'title': 'Mine now'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Conversation.objects.get(pk=convo).title, 'Heist club')


MSG = '/api/messaging/messages/'


class GroupChatFeatureTests(APITestCase):
    """Replies, reactions, pins, polls, media and the creator's leave flows."""

    def setUp(self):
        import tempfile

        from django.test import override_settings

        self._media = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media.enable()
        self.addCleanup(self._media.disable)
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        befriend(self.me, self.ana)
        befriend(self.me, self.ben)
        self.client.force_authenticate(self.me)
        self.group = self.client.post(
            BASE,
            {'kind': 'group', 'title': 'scorsese gang', 'member_ids': [self.ana.id, self.ben.id]},
            format='json',
        ).json()
        self.messages = f"{BASE}{self.group['id']}/messages/"

    def send(self, **data):
        return self.client.post(self.messages, data, format='json')

    def as_user(self, user):
        self.client.force_authenticate(user)

    def detail(self):
        return self.client.get(f"{BASE}{self.group['id']}/").json()

    def test_reply_reaction_and_allowed_reactions(self):
        first = self.send(body='yoo').json()
        reply = self.send(body='same', reply_to=first['id']).json()
        self.assertEqual(reply['reply_to']['id'], first['id'])
        self.assertEqual(reply['reply_to']['snippet'], 'yoo')

        url = f"{MSG}{first['id']}/react/"
        reacted = self.client.post(url, {'emoji': '😂'}, format='json').json()
        self.assertEqual(reacted['reactions'], [{'emoji': '😂', 'count': 1, 'me': True}])
        again = self.client.post(url, {'emoji': '😂'}, format='json').json()
        self.assertEqual(again['reactions'], [])

        movie = self.send(
            kind='movie',
            payload={'movie': {'id': 1, 'title': 'Goodfellas', 'year': '1990'}},
            allowed_reactions=['🍿', '🔥'],
        ).json()
        self.assertEqual(movie['payload']['movie']['title'], 'Goodfellas')
        refused = self.client.post(f"{MSG}{movie['id']}/react/", {'emoji': '😂'}, format='json')
        self.assertEqual(refused.json()['code'], 'reaction_not_allowed')
        self.assertEqual(
            self.client.post(f"{MSG}{movie['id']}/react/", {'emoji': '🍿'}, format='json').status_code,
            200,
        )

    def test_poll_votes_one_choice_and_toggle(self):
        poll = self.send(kind='poll', payload={'poll': {'question': 'Friday?', 'options': ['Yes', 'No']}}).json()
        self.assertEqual(poll['payload']['poll']['votes'], [0, 0])
        url = f"{MSG}{poll['id']}/vote/"
        self.assertEqual(self.client.post(url, {'option': 0}, format='json').json()['payload']['poll']['votes'], [1, 0])
        moved = self.client.post(url, {'option': 1}, format='json').json()['payload']['poll']
        self.assertEqual((moved['votes'], moved['my_vote']), ([0, 1], 1))
        cleared = self.client.post(url, {'option': 1}, format='json').json()['payload']['poll']
        self.assertEqual((cleared['votes'], cleared['my_vote']), ([0, 0], None))
        bad = self.send(kind='poll', payload={'poll': {'question': 'Q', 'options': ['only one']}})
        self.assertEqual(bad.json()['code'], 'invalid_poll')

    def test_photo_message_is_uploaded(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        photo = SimpleUploadedFile('shot.png', PNG, content_type='image/png')
        response = self.client.post(
            self.messages,
            {'kind': 'photo', 'body': 'look', 'attachment': photo, 'allowed_reactions': '["❤️"]'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertIn('message_media/', response.json()['attachment'])
        self.assertEqual(response.json()['allowed_reactions'], ['❤️'])

    def test_only_the_creator_pins_and_pinning_leaves_a_system_line(self):
        message = self.send(body='rules').json()
        self.as_user(self.ana)
        self.assertEqual(self.client.post(f"{MSG}{message['id']}/pin/").status_code, 403)
        self.as_user(self.me)
        self.assertTrue(self.client.post(f"{MSG}{message['id']}/pin/").json()['pinned'])
        last = self.client.get(self.messages).json()[-1]
        self.assertEqual((last['kind'], last['payload']['event']), ('system', 'pinned'))

    def test_remove_member_and_make_heritage(self):
        gid = self.group['id']
        removed = self.client.post(f'{BASE}{gid}/members/{self.ben.id}/remove/').json()
        self.assertEqual({m['id'] for m in removed['members']}, {self.me.id, self.ana.id})
        handed = self.client.post(f'{BASE}{gid}/owner/', {'user_id': self.ana.id}, format='json').json()
        self.assertEqual((handed['created_by'], handed['heritage']), (self.ana.id, True))
        # I am a regular member now.
        self.assertEqual(self.client.post(f'{BASE}{gid}/owner/', {'user_id': self.ana.id}).status_code, 403)

    def test_creator_must_choose_before_leaving_and_can_pass_the_tag(self):
        gid = self.group['id']
        response = self.client.post(f'{BASE}{gid}/leave/')
        self.assertEqual(response.json()['code'], 'owner_must_choose')
        self.assertEqual(self.client.post(f'{BASE}{gid}/leave/', {'pass_to': self.ben.id}).status_code, 204)
        self.as_user(self.ben)
        data = self.detail()
        self.assertEqual((data['created_by'], data['heritage']), (self.ben.id, True))
        self.assertNotIn(self.me.id, {m['id'] for m in data['members']})

    def test_regular_member_leaves(self):
        self.as_user(self.ana)
        self.assertEqual(self.client.post(f"{BASE}{self.group['id']}/leave/").status_code, 204)
        self.as_user(self.me)
        self.assertEqual(len(self.detail()['members']), 2)

    def _end_vote(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import GroupVote

        GroupVote.objects.filter(conversation_id=self.group['id']).update(
            ends_at=timezone.now() - timedelta(seconds=1)
        )

    def test_group_vote_keeps_the_group_then_picks_an_owner(self):
        gid = self.group['id']
        started = self.client.post(f'{BASE}{gid}/vote/').json()
        self.assertEqual(started['vote']['stage'], 'keep')
        own = self.client.post(f'{BASE}{gid}/vote/ballot/', {'choice': 'stay'})
        self.assertEqual(own.json()['code'], 'own_vote')
        self.as_user(self.ana)
        self.client.post(f'{BASE}{gid}/vote/ballot/', {'choice': 'stay'})
        self._end_vote()
        data = self.detail()
        self.assertEqual(data['vote']['stage'], 'owner')
        mine = self.client.post(f'{BASE}{gid}/vote/ballot/', {'choice': str(self.ana.id)})
        self.assertEqual(mine.json()['code'], 'invalid_choice')
        self.client.post(f'{BASE}{gid}/vote/ballot/', {'choice': str(self.ben.id)})
        self._end_vote()
        data = self.detail()
        self.assertIsNone(data['vote'])
        self.assertEqual((data['created_by'], data['heritage']), (self.ben.id, True))
        self.assertNotIn(self.me.id, {m['id'] for m in data['members']})

    def test_group_vote_can_delete_the_group_or_be_cancelled(self):
        gid = self.group['id']
        self.client.post(f'{BASE}{gid}/vote/')
        cancelled = self.client.delete(f'{BASE}{gid}/vote/').json()
        self.assertIsNone(cancelled['vote'])
        self.client.post(f'{BASE}{gid}/vote/')
        self.as_user(self.ana)
        self.client.post(f'{BASE}{gid}/vote/ballot/', {'choice': 'delete'})
        self._end_vote()
        self.assertEqual(self.client.get(f'{BASE}{gid}/').status_code, 404)
        self.assertFalse(Conversation.objects.filter(pk=gid).exists())


class ChatBasicsTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.ben = User.objects.create_user(username='ben', password='pw-123456')
        befriend(self.me, self.ana)
        befriend(self.me, self.ben)
        self.client.force_authenticate(self.me)
        self.direct = self.client.post(BASE, {'kind': 'direct', 'user_id': self.ana.id}, format='json').json()['id']

    def send(self, convo, body, user=None):
        if user is not None:
            self.client.force_authenticate(user)
        response = self.client.post(f'{BASE}{convo}/messages/', {'body': body}, format='json')
        self.client.force_authenticate(self.me)
        return response

    def row(self, convo):
        return next((c for c in self.client.get(BASE).json() if c['id'] == convo), None)

    def test_mute_pin_and_mark_unread(self):
        group = self.client.post(BASE, {'kind': 'group', 'title': 'G', 'member_ids': [self.ana.id]},
                                 format='json').json()['id']
        response = self.client.patch(f'{BASE}{self.direct}/settings/', {'pinned': True, 'muted': True},
                                     format='json')
        self.assertTrue(response.json()['pinned'])
        self.assertTrue(response.json()['muted'])
        # The pinned chat comes first even though the group is newer.
        self.assertEqual(self.client.get(BASE).json()[0]['id'], self.direct)
        self.client.patch(f'{BASE}{group}/settings/', {'unread': True}, format='json')
        self.assertTrue(self.row(group)['marked_unread'])
        self.client.get(f'{BASE}{group}/messages/')
        self.assertFalse(self.row(group)['marked_unread'])

    def test_clear_history_is_only_for_me(self):
        self.send(self.direct, 'old')
        self.client.post(f'{BASE}{self.direct}/clear/')
        self.assertEqual(self.client.get(f'{BASE}{self.direct}/messages/').json(), [])
        self.assertIsNone(self.row(self.direct)['last_message'])
        self.send(self.direct, 'new', user=self.ana)
        bodies = [m['body'] for m in self.client.get(f'{BASE}{self.direct}/messages/').json()]
        self.assertEqual(bodies, ['new'])
        self.client.force_authenticate(self.ana)
        self.assertEqual(len(self.client.get(f'{BASE}{self.direct}/messages/').json()), 2)

    def test_deleted_chat_comes_back_on_a_new_message(self):
        self.send(self.direct, 'hi')
        self.assertEqual(self.client.post(f'{BASE}{self.direct}/delete/').status_code, 204)
        self.assertIsNone(self.row(self.direct))
        self.send(self.direct, 'still there?', user=self.ana)
        row = self.row(self.direct)
        self.assertEqual(row['last_message']['body'], 'still there?')
        self.assertEqual(row['unread'], 1)

    def test_groups_are_left_not_deleted(self):
        group = self.client.post(BASE, {'kind': 'group', 'title': 'G', 'member_ids': [self.ana.id]},
                                 format='json').json()['id']
        self.assertEqual(self.client.post(f'{BASE}{group}/delete/').json()['code'], 'group_chat')

    def test_block_stops_both_sides_until_unblocked(self):
        self.client.post(f'/api/messaging/blocks/{self.ana.id}/')
        self.assertEqual(self.row(self.direct)['block'], 'me')
        self.assertEqual(self.send(self.direct, 'x').json()['code'], 'you_blocked')
        self.assertEqual(self.send(self.direct, 'x', user=self.ana).json()['code'], 'blocked')
        self.assertEqual([u['username'] for u in self.client.get('/api/messaging/blocks/').json()], ['ana'])
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.row(self.direct)['block'], 'them')
        self.client.force_authenticate(self.me)
        self.client.delete(f'/api/messaging/blocks/{self.ana.id}/')
        self.assertIsNone(self.row(self.direct)['block'])
        self.assertEqual(self.send(self.direct, 'back').status_code, 201)

    def test_edit_and_delete_own_message(self):
        mine = self.send(self.direct, 'helo').json()['id']
        theirs = self.send(self.direct, 'yo', user=self.ana).json()['id']
        edited = self.client.patch(f'/api/messaging/messages/{mine}/', {'body': 'hello'}, format='json').json()
        self.assertEqual(edited['body'], 'hello')
        self.assertTrue(edited['edited'])
        self.assertEqual(self.client.patch(f'/api/messaging/messages/{theirs}/', {'body': 'no'},
                                           format='json').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/messaging/messages/{theirs}/').status_code, 403)
        gone = self.client.delete(f'/api/messaging/messages/{mine}/').json()
        self.assertTrue(gone['deleted'])
        self.assertEqual(gone['body'], '')

    def test_group_owner_deletes_any_message_and_adds_members(self):
        group = self.client.post(BASE, {'kind': 'group', 'title': 'G', 'member_ids': [self.ana.id]},
                                 format='json').json()['id']
        theirs = self.send(group, 'spam', user=self.ana).json()['id']
        self.assertTrue(self.client.delete(f'/api/messaging/messages/{theirs}/').json()['deleted'])
        response = self.client.post(f'{BASE}{group}/members/', {'user_ids': [self.ben.id]}, format='json')
        self.assertEqual({m['username'] for m in response.json()['members']}, {'me', 'ana', 'ben'})
        self.assertEqual(Message.objects.filter(conversation_id=group, kind='system').last().payload,
                         {'event': 'added', 'target': 'ben'})
        # Ben starts with only the "added" line unread; Ana cannot add people.
        self.client.force_authenticate(self.ben)
        self.assertEqual(self.row(group)['unread'], 1)
        self.client.force_authenticate(self.ana)
        response = self.client.post(f'{BASE}{group}/members/', {'user_ids': [self.ben.id]}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_report_and_seen(self):
        msg = self.send(self.direct, 'hi').json()['id']
        response = self.client.post(f'{BASE}{self.direct}/report/', {'reason': 'spam', 'message_id': msg},
                                    format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post(f'{BASE}{self.direct}/report/', {'reason': 'nope'},
                                          format='json').status_code, 400)
        self.assertIsNone(self.row(self.direct)['seen_at'])
        self.client.force_authenticate(self.ana)
        self.client.get(f'{BASE}{self.direct}/messages/')
        self.client.force_authenticate(self.me)
        self.assertIsNotNone(self.row(self.direct)['seen_at'])
