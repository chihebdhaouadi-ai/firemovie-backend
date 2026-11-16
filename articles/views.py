from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Article
from .news_source import latest_movie_news


def _published():
    return Article.objects.filter(published=True)


class LatestArticlesView(APIView):
    """Public list of the latest movie news cards from the IMDb232 feed, newest first."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(latest_movie_news())


def article_detail(request, slug):
    article = get_object_or_404(_published(), slug=slug)
    return render(request, 'articles/detail.html', {
        'article': article,
        'body_url': reverse('articles:body', args=[article.slug]),
    })


@xframe_options_sameorigin
def article_body(request, slug):
    """The raw HTML and CSS of an article, as its own document."""
    article = get_object_or_404(_published(), slug=slug)
    content = article.body
    if '<html' not in content.lower():
        content = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'</head><body>{content}</body></html>'
        )
    return HttpResponse(content, content_type='text/html; charset=utf-8')
