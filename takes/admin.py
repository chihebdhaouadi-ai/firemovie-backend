from django.contrib import admin

from .models import FilmReaction, Take, TakeComment, TakeReport, TakeVote


@admin.register(FilmReaction)
class FilmReactionAdmin(admin.ModelAdmin):
    list_display = ('film_id', 'user', 'reaction', 'updated_at')
    list_filter = ('reaction',)


@admin.register(Take)
class TakeAdmin(admin.ModelAdmin):
    list_display = ('film_id', 'author', 'reaction', 'created_at')
    list_filter = ('reaction',)


@admin.register(TakeVote)
class TakeVoteAdmin(admin.ModelAdmin):
    list_display = ('take', 'user', 'kind', 'created_at')
    list_filter = ('kind',)


@admin.register(TakeComment)
class TakeCommentAdmin(admin.ModelAdmin):
    list_display = ('take', 'author', 'created_at')


@admin.register(TakeReport)
class TakeReportAdmin(admin.ModelAdmin):
    list_display = ('take', 'reporter', 'reason', 'created_at')
    list_filter = ('reason',)
    search_fields = ('details', 'take__body', 'reporter__username')
