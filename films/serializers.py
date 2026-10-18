from rest_framework import serializers


class AddMovieSerializer(serializers.Serializer):
    imdbid = serializers.CharField(max_length=20)


class ImdbIdParamSerializer(serializers.Serializer):
    imdbid = serializers.CharField(max_length=20, required=False)