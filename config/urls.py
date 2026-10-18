from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/account/', include('accounts.urls')),
    path('api/film/', include('films.urls')),
    path('api/review/', include('reviews.urls')),
]