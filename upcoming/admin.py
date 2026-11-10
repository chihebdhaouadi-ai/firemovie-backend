from django.contrib import admin

from .models import UpcomingFilm


@admin.register(UpcomingFilm)
class UpcomingFilmAdmin(admin.ModelAdmin):
    list_display = ('title', 'release_date', 'published', 'updated_at')
    list_filter = ('published',)
    search_fields = ('title',)
    list_editable = ('published',)
    readonly_fields = ('created_at', 'updated_at')
