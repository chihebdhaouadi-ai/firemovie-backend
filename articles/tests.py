import json
import shutil
import tempfile
from unittest import mock
from urllib.error import URLError

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
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


def news_edge(node_id, title='Headline', image='https://img.example.com/a.jpg',
              url='https://variety.com/a', date='2026-11-13T19:05:59Z'):
    return {'node': {
        'id': node_id,
        'articleTitle': {'plainText': title},
        'image': {'url': image} if image is not None else None,
        'externalUrl': url,
        'date': date,
    }}


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode('utf-8')

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@override_settings(IMDB232_RAPIDAPI_KEY='test-key')
class LatestArticlesApiTests(APITestCase):
    def setUp(self):
        cache.clear()

    def _get(self, edges):
        payload = {'data': {'news': {'edges': edges}}}
        with mock.patch('articles.news_source.urlopen', return_value=FakeResponse(payload)) as urlopen:
            response = self.client.get(reverse('articles_latest'))
        return response, urlopen

    def test_maps_news_to_the_app_card_shape_without_login(self):
        response, urlopen = self._get([news_edge('ni66110184', title='Margot Robbie stars')])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{
            'id': 66110184,
            'title': 'Margot Robbie stars',
            'cover_url': 'https://img.example.com/a.jpg',
            'url': 'https://variety.com/a',
            'published_at': '2026-11-13T19:05:59Z',
        }])
        request = urlopen.call_args.args[0]
        self.assertIn('category=MOVIE', request.full_url)
        self.assertIn('limit=25', request.full_url)
        self.assertEqual(request.get_header('X-rapidapi-key'), 'test-key')
        self.assertEqual(request.get_header('X-rapidapi-host'), 'imdb232.p.rapidapi.com')

    def test_skips_items_missing_required_fields_or_not_https(self):
        response, _ = self._get([
            news_edge('ni1', image=None),
            news_edge('ni2', url='http://insecure.example.com/x'),
            news_edge('abc', title='Bad id'),
            news_edge('ni4', title='Good'),
        ])
        self.assertEqual([item['id'] for item in response.json()], [4])

    def test_response_is_cached_between_requests(self):
        edges = [news_edge('ni5')]
        _, first = self._get(edges)
        second_response, second = self._get(edges)
        self.assertEqual(first.call_count, 1)
        self.assertEqual(second.call_count, 0)
        self.assertEqual(len(second_response.json()), 1)

    def test_empty_when_key_is_not_configured(self):
        with override_settings(IMDB232_RAPIDAPI_KEY=''):
            with mock.patch('articles.news_source.urlopen') as urlopen:
                response = self.client.get(reverse('articles_latest'))
        self.assertEqual(response.json(), [])
        urlopen.assert_not_called()

    def test_upstream_failure_returns_502(self):
        with mock.patch('articles.news_source.urlopen', side_effect=URLError('down')):
            response = self.client.get(reverse('articles_latest'))
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['code'], 'news_unavailable')


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
