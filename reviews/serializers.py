from rest_framework import serializers
from .models import Review


class ReviewSerializer(serializers.ModelSerializer):
    date = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = Review
        fields = ('id', 'imdb_id', 'rating', 'body', 'writer_name',
                  'writer_image', 'likes', 'dislikes', 'date')


class ReviewInputSerializer(serializers.Serializer):
    imdb_id = serializers.CharField(max_length=20)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    body = serializers.CharField(required=False, allow_blank=True)