from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User

from .models import FriendRequest, Notification
from .serializers import (
    FriendRequestCreateSerializer,
    MovieSuggestionCreateSerializer,
    NotificationSerializer,
    UserCardSerializer,
)
from .services import (
    accept_friend_request,
    remove_friend_request,
    send_friend_request,
    send_movie_suggestions,
)

SEARCH_MIN_LENGTH = 2
SEARCH_LIMIT = 20
NOTIFICATIONS_LIMIT = 50


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_search(request):
    query = request.query_params.get('q', '').strip()
    if len(query) < SEARCH_MIN_LENGTH:
        return Response([])
    users = (
        User.objects.filter(username__icontains=query)
        .exclude(pk=request.user.pk)
        .order_by('username', 'id')[:SEARCH_LIMIT]
    )
    return Response(UserCardSerializer(users, many=True, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def connections(request):
    me = request.user
    following = User.objects.filter(follower_links__follower=me).order_by('username', 'id')
    followers = User.objects.filter(following_links__following=me).order_by('username', 'id')
    friends = (
        User.objects.filter(
            Q(sent_friend_requests__receiver=me, sent_friend_requests__status=FriendRequest.Status.ACCEPTED)
            | Q(received_friend_requests__sender=me, received_friend_requests__status=FriendRequest.Status.ACCEPTED)
        )
        .distinct()
        .order_by('username', 'id')
    )
    context = {'request': request}
    return Response({
        'following': UserCardSerializer(following, many=True, context=context).data,
        'followers': UserCardSerializer(followers, many=True, context=context).data,
        'friends': UserCardSerializer(friends, many=True, context=context).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_friend_request(request):
    serializer = FriendRequestCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    receiver = get_object_or_404(User, pk=serializer.validated_data['user_id'])
    friend_request = send_friend_request(request.user, receiver)
    return Response(
        {'id': friend_request.pk, 'status': friend_request.status},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_movie_suggestions(request):
    serializer = MovieSuggestionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    sent = send_movie_suggestions(
        request.user,
        data['recipient_ids'],
        film_id=data['film_id'],
        film_title=data['film_title'],
        film_year=data.get('film_year'),
        film_poster_url=data['film_poster_url'],
        comment=data['comment'],
    )
    return Response({'sent': sent}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_request(request, request_id):
    friend_request = get_object_or_404(
        FriendRequest,
        pk=request_id,
        receiver=request.user,
        status=FriendRequest.Status.PENDING,
    )
    accept_friend_request(friend_request)
    return Response({'status': FriendRequest.Status.ACCEPTED})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def decline_request(request, request_id):
    friend_request = get_object_or_404(
        FriendRequest,
        pk=request_id,
        receiver=request.user,
        status=FriendRequest.Status.PENDING,
    )
    remove_friend_request(friend_request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_request(request, request_id):
    friend_request = get_object_or_404(
        FriendRequest,
        pk=request_id,
        sender=request.user,
        status=FriendRequest.Status.PENDING,
    )
    remove_friend_request(friend_request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def notifications(request):
    mine = Notification.objects.filter(recipient=request.user)
    items = mine.select_related('actor', 'suggestion')[:NOTIFICATIONS_LIMIT]
    return Response({
        'unread_count': mine.filter(read=False).count(),
        'results': NotificationSerializer(items, many=True, context={'request': request}).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_notifications_read(request):
    Notification.objects.filter(recipient=request.user, read=False).update(read=True)
    return Response(status=status.HTTP_204_NO_CONTENT)
