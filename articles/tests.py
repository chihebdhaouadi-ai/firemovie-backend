import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from .models import Article

HTML_BODY = '<h2 class="lead">Hello</h2><style>.lead{color:red}</style>'


def _cover(name='cover.jpg'):
    return SimpleUploadedFile(name, b'\xff\xd8\xff fake jpeg', content_type='image/jpeg')


class ArticleTestCase(TestCase):
    def setUp(self):
        self._media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self._media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self._media, ignore_errors=True)

    def make(self, title, **kwargs):
        return Article.objects.create(
            title=title, body=kwargs.pop('body', HTML_BODY), cover=_cover(), **kwargs,
        )


class ArticleModelTests(ArticleTestCase):
    def test_slug_is_generated_and_made_unique(self):
        first = self.make('Cannes Diary')
        second = self.make('Cannes Diary')
        self.assertEqual(first.slug, 'cannes-diary')
        self.assertEqual(second.slug, 'cannes-diary-2')


class LatestArticlesApiTests(ArticleTestCase, APITestCase):
    def test_lists_only_published_newest_first_without_login(self):
        old = self.make('Old one', published_at=timezone.now() - timedelta(days=3))
        new = self.make('New one', published_at=timezone.now())
        self.make('Draft', published=False)

        response = self.client.get(reverse('articles_latest'))

        self.assertEqual(response.status_code, 200)
        titles = [item['title'] for item in response.json()]
        self.assertEqual(titles, ['New one', 'Old one'])
        item = response.json()[0]
        self.assertEqual(item['id'], new.id)
        self.assertTrue(item['cover_url'].startswith('http://testserver/'))
        self.assertEqual(item['url'], f'http://testserver/articles/{new.slug}/')
        self.assertNotIn('body', item)
        self.assertEqual(old.slug, 'old-one')

    def test_empty_when_nothing_published(self):
        self.make('Draft', published=False)
        response = self.client.get(reverse('articles_latest'))
        self.assertEqual(response.json(), [])


class ArticlePageTests(ArticleTestCase):
    def test_published_article_page_embeds_the_body_frame(self):
        article = self.make('Film Notes')
        response = self.client.get(article.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Film Notes')
        self.assertContains(response, reverse('articles:body', args=[article.slug]))

    def test_body_is_served_as_its_own_document_and_allowed_in_same_origin_frame(self):
        article = self.make('Framed')
        response = self.client.get(reverse('articles:body', args=[article.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn('text/html', response['Content-Type'])
        self.assertContains(response, '<style>.lead{color:red}</style>')
        self.assertContains(response, '<!doctype html>')

    def test_full_html_document_is_not_wrapped_twice(self):
        full = '<html><head><title>x</title></head><body>Hi</body></html>'
        article = self.make('Full doc', body=full)
        response = self.client.get(reverse('articles:body', args=[article.slug]))
        self.assertEqual(response.content.decode().count('<html'), 1)

    def test_unpublished_article_is_not_found(self):
        article = self.make('Hidden', published=False)
        self.assertEqual(self.client.get(article.get_absolute_url()).status_code, 404)
        self.assertEqual(
            self.client.get(reverse('articles:body', args=[article.slug])).status_code, 404,
        )
