from django.contrib import admin

from .models import Conversation, Membership, Message


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'kind', 'title', 'created_by', 'updated_at')
    list_filter = ('kind',)
    inlines = [MembershipInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'created_at')
    search_fields = ('body',)
