from rest_framework import serializers

from .models import TOP5_SIZE, FilmEntry

FILM_ID_PATTERN = r'^(tt\d{1,10}|\d{1,12})$'


class FilmIdField(serializers.RegexField):
    def __init__(self, **kwargs):
        super().__init__(FILM_ID_PATTERN, max_length=64, **kwargs)


class AddFilmSerializer(serializers.Serializer):
    film_id = FilmIdField()


class AddTop5Serializer(serializers.Serializer):
    film_id = FilmIdField()
    slot = serializers.IntegerField(min_value=1, max_value=TOP5_SIZE, required=False)
    replace = serializers.BooleanField(default=False)


class MoveTop5Serializer(serializers.Serializer):
    slot = serializers.IntegerField(min_value=1, max_value=TOP5_SIZE)


class EntrySerializer(serializers.ModelSerializer):
    slot = serializers.IntegerField(source='slot_index', read_only=True)

    class Meta:
        model = FilmEntry
        fields = ('film_id', 'list_type', 'slot', 'created_at')
