import datetime
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import UpcomingFilm


def _poster():
    return SimpleUploadedFile('poster.jpg', b'fake-image', content_type='image/jpeg')


_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_MEDIA)
class UpcomingFilmsApiTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        today = timezone.localdate()
        self.soon = UpcomingFilm.objects.create(
            title='Soon', poster=_poster(),
            release_date=today + datetime.timedelta(days=5),
            description='Coming soon.',
        )
        self.later = UpcomingFilm.objects.create(
            title='Later', poster=_poster(),
            release_date=today + datetime.timedelta(days=20),
        )
        UpcomingFilm.objects.create(
            title='Hidden', poster=_poster(),
            release_date=today + datetime.timedelta(days=3), published=False,
        )
        UpcomingFilm.objects.create(
            title='Past', poster=_poster(),
            release_date=today - datetime.timedelta(days=1),
        )

    def test_lists_published_future_films_soonest_first(self):
        res = self.client.get('/api/upcoming/')
        self.assertEqual(res.status_code, 200)
        titles = [f['title'] for f in res.json()]
        self.assertEqual(titles, ['Soon', 'Later'])

    def test_item_has_poster_url_date_and_description(self):
        item = self.client.get('/api/upcoming/').json()[0]
        self.assertEqual(item['title'], 'Soon')
        self.assertEqual(item['release_date'], self.soon.release_date.isoformat())
        self.assertEqual(item['description'], 'Coming soon.')
        self.assertTrue(item['poster_url'].startswith('http'))
        self.assertIn('/upcoming/posters/', item['poster_url'])
