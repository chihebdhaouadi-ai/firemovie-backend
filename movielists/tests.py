import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from social.models import FriendRequest

from .models import MAX_FILMS, MovieList

URL = '/api/movie-lists/'


def film(n, poster=True):
    return {
        'film_id': f'tt{1000000 + n}',
        'title': f'Film {n}',
        'poster_url': f'https://img.test/{n}.jpg' if poster else None,
    }


class MovieListTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.me = User.objects.create_user(username='me', password='pw-123456')
        self.ana = User.objects.create_user(username='ana', password='pw-123456')
        self.zed = User.objects.create_user(username='zed', password='pw-123456')
        FriendRequest.objects.create(sender=self.me, receiver=self.ana, status=FriendRequest.Status.ACCEPTED)
        self.client.force_authenticate(self.me)

    def post_list(self, name='Heist films', films=None):
        if films is None:
            films = [film(1), film(2)]
        return self.client.post(URL, {'name': name, 'films': films}, format='json')

    def test_posting_a_list_returns_it_with_its_films_in_order(self):
        response = self.post_list(films=[film(3), film(1), film(2, poster=False)])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Heist films')
        self.assertTrue(response.data['is_mine'])
        self.assertEqual([f['film_id'] for f in response.data['films']], ['tt1000003', 'tt1000001', 'tt1000002'])
        self.assertEqual(response.data['film_count'], 3)
        # The stacked cover only uses films that have a poster.
        self.assertEqual(response.data['posters'], ['https://img.test/3.jpg', 'https://img.test/1.jpg'])

    def test_a_list_needs_a_name_and_at_least_one_valid_film(self):
        self.assertEqual(self.post_list(name='   ').status_code, 400)
        self.assertEqual(self.post_list(films=[]).status_code, 400)
        self.assertEqual(self.post_list(films=[{'film_id': 'nope', 'title': 'x'}]).status_code, 400)
        too_many = [film(n) for n in range(MAX_FILMS + 1)]
        self.assertEqual(self.post_list(films=too_many).status_code, 400)

    def test_duplicate_films_are_kept_once(self):
        response = self.post_list(films=[film(1), film(1), film(2)])

        self.assertEqual(response.data['film_count'], 2)

    def test_my_lists_show_only_mine_newest_first(self):
        self.post_list(name='First')
        self.post_list(name='Second')
        MovieList.objects.create(owner=self.ana, name='Not mine')

        names = [item['name'] for item in self.client.get(URL).data['data']]

        self.assertEqual(names, ['Second', 'First'])

    def test_friends_lists_show_friends_but_not_strangers_or_mine(self):
        MovieList.objects.create(owner=self.ana, name='Ana picks')
        MovieList.objects.create(owner=self.zed, name='Stranger picks')
        self.post_list(name='Mine')

        data = self.client.get(URL + 'friends/').data['data']

        self.assertEqual([item['name'] for item in data], ['Ana picks'])
        self.assertEqual(data[0]['owner']['username'], 'ana')

    def test_only_the_owner_can_rename_or_delete(self):
        theirs = MovieList.objects.create(owner=self.ana, name='Ana picks')
        mine = self.post_list().data['id']

        self.assertEqual(self.client.patch(f'{URL}{theirs.id}/', {'name': 'x'}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f'{URL}{theirs.id}/').status_code, 403)
        renamed = self.client.patch(f'{URL}{mine}/', {'name': 'Better name'}, format='json')
        self.assertEqual(renamed.data['name'], 'Better name')
        self.assertEqual(renamed.data['film_count'], 2)
        self.assertEqual(self.client.delete(f'{URL}{mine}/').status_code, 204)
        self.assertFalse(MovieList.objects.filter(pk=mine).exists())

    def test_hearts_count_once_and_work_on_your_own_list(self):
        theirs = MovieList.objects.create(owner=self.ana, name='Ana picks')
        mine = self.post_list().data['id']

        liked = self.client.put(f'{URL}{theirs.id}/like/', {'active': True}, format='json')
        self.client.put(f'{URL}{theirs.id}/like/', {'active': True}, format='json')
        self.assertEqual((liked.data['likes'], liked.data['liked']), (1, True))
        again = self.client.get(f'{URL}{theirs.id}/').data
        self.assertEqual(again['likes'], 1)
        unliked = self.client.put(f'{URL}{theirs.id}/like/', {'active': False}, format='json')
        self.assertEqual((unliked.data['likes'], unliked.data['liked']), (0, False))
        own = self.client.put(f'{URL}{mine}/like/', {'active': True}, format='json')
        self.assertEqual(own.status_code, 200)
        self.assertEqual((own.data['likes'], own.data['liked']), (1, True))

    def test_comments_are_added_and_counted(self):
        theirs = MovieList.objects.create(owner=self.ana, name='Ana picks')

        posted = self.client.post(f'{URL}{theirs.id}/comments/', {'body': 'Great picks!'}, format='json')
        self.assertEqual(posted.status_code, 201)
        self.assertEqual(posted.data['author']['username'], 'me')
        self.assertEqual(self.client.post(f'{URL}{theirs.id}/comments/', {'body': ''}, format='json').status_code, 400)

        listed = self.client.get(f'{URL}{theirs.id}/comments/').data['data']
        self.assertEqual([c['body'] for c in listed], ['Great picks!'])
        self.assertEqual(self.client.get(f'{URL}{theirs.id}/').data['comments'], 1)
        self.assertTrue(listed[0]['is_mine'])
        self.assertFalse(listed[0]['is_writer'])
        self.assertIsNone(listed[0]['parent_id'])

    def test_replies_point_at_their_comment_and_the_owner_is_the_writer(self):
        theirs = MovieList.objects.create(owner=self.ana, name='Ana picks')
        top = self.client.post(f'{URL}{theirs.id}/comments/', {'body': 'Why no Heat?'}, format='json').data

        self.client.force_authenticate(self.ana)
        reply = self.client.post(
            f'{URL}{theirs.id}/comments/', {'body': 'Next time!', 'parent_id': top['id']}, format='json',
        )
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data['parent_id'], top['id'])
        self.assertTrue(reply.data['is_writer'])

        other = MovieList.objects.create(owner=self.zed, name='Zed picks')
        stray = self.client.post(
            f'{URL}{other.id}/comments/', {'body': 'Hi', 'parent_id': top['id']}, format='json',
        )
        self.assertEqual(stray.status_code, 400)
        self.assertEqual(self.client.get(f'{URL}{theirs.id}/').data['comments'], 2)

    def test_a_comment_can_be_just_a_photo(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        theirs = MovieList.objects.create(owner=self.ana, name='Ana picks')
        photo = SimpleUploadedFile('still.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32, content_type='image/png')

        with override_settings(MEDIA_ROOT=media):
            posted = self.client.post(f'{URL}{theirs.id}/comments/', {'image': photo}, format='multipart')
        self.assertEqual(posted.status_code, 201)
        self.assertEqual(posted.data['body'], '')
        self.assertIn('list_comments/', posted.data['image_url'])

        text = SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')
        bad = self.client.post(f'{URL}{theirs.id}/comments/', {'image': text}, format='multipart')
        self.assertEqual(bad.status_code, 400)

    def test_saving_someone_elses_list_puts_it_in_your_saved_lists(self):
        first = MovieList.objects.create(owner=self.ana, name='Cry every time')
        second = MovieList.objects.create(owner=self.zed, name='Heists')

        saved = self.client.put(f'{URL}{first.id}/save/', {'active': True}, format='json')
        self.client.put(f'{URL}{second.id}/save/', {'active': True}, format='json')
        # Saving twice keeps one save.
        self.client.put(f'{URL}{first.id}/save/', {'active': True}, format='json')

        self.assertEqual(saved.status_code, 200)
        self.assertTrue(saved.data['saved'])
        listed = self.client.get(f'{URL}saved/').data['data']
        self.assertEqual([item['name'] for item in listed], ['Heists', 'Cry every time'])
        self.assertTrue(self.client.get(f'{URL}{first.id}/').data['saved'])

        unsaved = self.client.put(f'{URL}{first.id}/save/', {'active': False}, format='json')
        self.assertFalse(unsaved.data['saved'])
        self.assertEqual([item['name'] for item in self.client.get(f'{URL}saved/').data['data']], ['Heists'])

    def test_you_cannot_save_your_own_list_and_saves_are_private(self):
        mine = self.post_list().data['id']
        theirs = MovieList.objects.create(owner=self.ana, name='Noir')

        self.assertEqual(self.client.put(f'{URL}{mine}/save/', {'active': True}, format='json').status_code, 400)
        self.client.put(f'{URL}{theirs.id}/save/', {'active': True}, format='json')
        self.client.force_authenticate(self.zed)
        self.assertEqual(self.client.get(f'{URL}saved/').data['data'], [])

    def test_sharing_a_list_posts_a_card_in_each_friends_chat(self):
        from messaging.models import Message

        list_id = self.post_list(name='Heist films').data['id']

        response = self.client.post(
            f'{URL}{list_id}/share/', {'recipient_ids': [self.ana.id], 'message': 'Watch these'}, format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['sent'], 1)
        card = Message.objects.get(kind=Message.Kind.LIST)
        self.assertEqual(card.sender, self.me)
        self.assertEqual(card.body, 'Watch these')
        self.assertEqual(card.payload['list']['id'], list_id)
        self.assertEqual(card.payload['list']['name'], 'Heist films')
        self.assertEqual(card.payload['list']['film_count'], 2)
        self.assertTrue(card.conversation.memberships.filter(user=self.ana).exists())

    def test_lists_are_only_shared_with_friends(self):
        list_id = self.post_list().data['id']

        response = self.client.post(f'{URL}{list_id}/share/', {'recipient_ids': [self.zed.id]}, format='json')

        self.assertEqual(response.status_code, 400)

    def test_lists_need_an_account(self):
        self.client.force_authenticate(None)

        self.assertEqual(self.client.get(URL).status_code, 401)
