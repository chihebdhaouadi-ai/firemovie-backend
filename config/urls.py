from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/account/', include('accounts.urls')),
    path('api/film/', include('films.urls')),
    path('api/lists/', include('films.list_urls')),
    path('api/films/', include('films.catalog_urls')),
    path('api/review/', include('reviews.urls')),
    path('api/social/', include('social.urls')),
    path('api/takes/', include('takes.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)