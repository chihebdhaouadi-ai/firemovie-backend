from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from .serializers import RegisterSerializer, LoginSerializer, UserSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    serializer = RegisterSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'message': serializer.errors,
            'feature': 'register',
            'status': 400,
        }, status=status.HTTP_400_BAD_REQUEST)
    user = serializer.save()
    Token.objects.get_or_create(user=user)
    return Response({
        'message': 'Account created',
        'feature': 'register',
        'status': 200,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response({
            'message': 'wrong',
            'feature': 'login',
            'status': 400,
        }, status=status.HTTP_400_BAD_REQUEST)

    user = serializer.validated_data['user']
    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'message': 'loged in',
        'feature': 'login',
        'status': 200,
        'token': token.key,
        'user': UserSerializer(user).data,
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile_view(request):
    return Response(UserSerializer(request.user).data)