from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('', include('landing.urls')),
    path('admin/', admin.site.urls),
    path('api/account/', include('accounts.urls')),
    path('api/film/', include('films.urls')),
    path('api/lists/', include('films.list_urls')),
    path('api/films/', include('films.catalog_urls')),
    path('api/review/', include('reviews.urls')),
    path('api/social/', include('social.urls')),
    path('api/takes/', include('takes.urls')),
    path('api/articles/', include('articles.api_urls')),
    path('api/upcoming/', include('upcoming.urls')),
    path('api/messaging/', include('messaging.urls')),
    path('articles/', include('articles.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)