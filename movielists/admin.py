from django.contrib import admin

from .models import MovieList, MovieListComment, MovieListItem


class ItemInline(admin.TabularInline):
    model = MovieListItem
    extra = 0


@admin.register(MovieList)
class MovieListAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'created_at')
    inlines = [ItemInline]


admin.site.register(MovieListComment)
