from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .models import Review
from .serializers import ReviewSerializer


@api_view(['GET'])
@permission_classes([AllowAny])
def get_reviews(request):
    imdb_id = request.query_params.get('imdbid')
    if not imdb_id:
        return Response({'status': 400, 'data': [], 'message': 'imdbid required'},
                        status=status.HTTP_400_BAD_REQUEST)

    reviews = Review.objects.filter(imdb_id=imdb_id)
    serializer = ReviewSerializer(reviews, many=True)

    ratings = [r.rating for r in reviews]
    avg = round(sum(ratings) / len(ratings), 1) if ratings else 0

    return Response({
        'status': 200,
        'data': serializer.data,
        'count': len(serializer.data),
        'moyen': avg,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_review(request):
    imdb_id = request.data.get('imdb_id')
    rating = request.data.get('rating')
    body = request.data.get('body', '')

    if not imdb_id or not rating:
        return Response({'status': 400, 'message': 'imdb_id and rating required'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            raise ValueError
    except (ValueError, TypeError):
        return Response({'status': 400, 'message': 'rating must be integer 1-5'},
                        status=status.HTTP_400_BAD_REQUEST)

    review = Review.objects.create(
        user=request.user,
        imdb_id=imdb_id,
        rating=rating,
        body=body,
        writer_name=request.user.username,
        writer_image='',
    )

    return Response({
        'status': 200,
        'message': 'Review created',
        'data': ReviewSerializer(review).data,
    })