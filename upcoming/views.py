from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny

from .models import UpcomingFilm

LIST_LIMIT = 20


class UpcomingFilmSerializer(serializers.ModelSerializer):
    poster_url = serializers.SerializerMethodField()

    class Meta:
        model = UpcomingFilm
        fields = ('id', 'title', 'poster_url', 'release_date', 'description')

    def get_poster_url(self, film):
        return self.context['request'].build_absolute_uri(film.poster.url)


class UpcomingFilmsView(generics.ListAPIView):
    """Public list of published films releasing from today on, soonest first."""

    serializer_class = UpcomingFilmSerializer
    permission_classes = [AllowAny]
    pagination_class = None

    def get_queryset(self):
        return UpcomingFilm.objects.filter(
            published=True,
            release_date__gte=timezone.localdate(),
        )[:LIST_LIMIT]
