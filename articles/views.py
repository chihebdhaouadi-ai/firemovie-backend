from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from .models import Article

LIST_LIMIT = 20


def _published():
    return Article.objects.filter(published=True)


class ArticleCardSerializer(serializers.ModelSerializer):
    cover_url = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ('id', 'title', 'slug', 'cover_url', 'url', 'published_at')

    def get_cover_url(self, article):
        return self.context['request'].build_absolute_uri(article.cover.url)

    def get_url(self, article):
        return self.context['request'].build_absolute_uri(article.get_absolute_url())


class LatestArticlesView(generics.ListAPIView):
    """Public list of the latest published articles, newest first."""

    serializer_class = ArticleCardSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        return _published()[:LIST_LIMIT]


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
