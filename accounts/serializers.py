from rest_framework import serializers
from django.contrib.auth import authenticate
from films.models import FilmEntry
from films.services import film_ids_for
from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password')

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, data):
        try:
            user = User.objects.get(email=data['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid credentials")
        if not user.check_password(data['password']):
            raise serializers.ValidationError("Invalid credentials")
        data['user'] = user
        return data


class UserSerializer(serializers.ModelSerializer):
    top_movies = serializers.SerializerMethodField()
    watched_movies = serializers.SerializerMethodField()
    watchlist_movies = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'balance',
                  'top_movies', 'watched_movies', 'watchlist_movies')

    def get_top_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.TOP_5)

    def get_watched_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.WATCHED)

    def get_watchlist_movies(self, obj):
        return film_ids_for(obj, FilmEntry.ListType.WATCHLIST)