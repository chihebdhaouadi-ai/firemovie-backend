import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User
from films.models import FilmEntry
from reviews.models import Review

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 16


class PublicProfileTests(APITestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username='viewer', email='viewer@example.com', password='pw-12345',
        )
        self.target = User.objects.create_user(
            username='target', email='target@example.com', password='pw-12345',
        )

    def url(self, user_id):
        return f'/api/account/users/{user_id}'

    def test_returns_username_and_counts_without_email(self):
        FilmEntry.objects.create(
            user=self.target, film_id='tt1', list_type=FilmEntry.ListType.WATCHED,
        )
        FilmEntry.objects.create(
            user=self.target, film_id='tt2', list_type=FilmEntry.ListType.WATCHED,
        )
        FilmEntry.objects.create(
            user=self.target, film_id='tt3', list_type=FilmEntry.ListType.WATCHLIST,
        )
        Review.objects.create(
            user=self.target, imdb_id='tt1', rating=4, writer_name='target',
        )
        self.client.force_authenticate(self.viewer)

        response = self.client.get(self.url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {
            'id': self.target.id,
            'username': 'target',
            'bio': '',
            'avatar': None,
            'cover': None,
            'stats': {'watched': 2, 'watchlist': 1, 'reviews': 1},
            'friendship': 'none',
            'friend_request_id': None,
            'followers': 0,
            'following': 0,
        })

    def test_requires_authentication(self):
        response = self.client.get(self.url(self.target.id))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_unknown_user_returns_not_found(self):
        self.client.force_authenticate(self.viewer)

        response = self.client.get(self.url(999999))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class RegisterTokenTests(APITestCase):
    def test_register_returns_a_token_that_authenticates(self):
        response = self.client.post('/api/account/register', {
            'username': 'newbie',
            'email': 'newbie@example.com',
            'password': 'pw-12345',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        profile = self.client.get('/api/account/profile')
        self.assertEqual(profile.status_code, status.HTTP_200_OK)
        self.assertEqual(profile.data['username'], 'newbie')


class ProfileUpdateTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='me', email='me@example.com', password='pw-12345',
        )
        self.client.force_authenticate(self.user)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_patch_saves_bio(self):
        response = self.client.patch(
            '/api/account/profile', {'bio': 'Noir fan'}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['bio'], 'Noir fan')
        self.user.refresh_from_db()
        self.assertEqual(self.user.bio, 'Noir fan')

    def test_bio_longer_than_limit_is_rejected(self):
        response = self.client.patch(
            '/api/account/profile', {'bio': 'x' * 281}, format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_png_avatar_and_cover_are_stored(self):
        response = self.client.patch('/api/account/profile', {
            'avatar': SimpleUploadedFile('me.png', PNG_BYTES, content_type='image/png'),
            'cover': SimpleUploadedFile('cover.png', PNG_BYTES, content_type='image/png'),
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.avatar.name.startswith('avatars/'))
        self.assertTrue(self.user.cover.name.startswith('covers/'))
        self.assertIn('/media/avatars/', response.data['avatar'])

    def test_file_that_is_not_an_image_is_rejected(self):
        response = self.client.patch('/api/account/profile', {
            'avatar': SimpleUploadedFile('fake.png', b'not an image', content_type='image/png'),
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_unsupported_extension_is_rejected(self):
        response = self.client.patch('/api/account/profile', {
            'avatar': SimpleUploadedFile('notes.txt', PNG_BYTES, content_type='text/plain'),
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
