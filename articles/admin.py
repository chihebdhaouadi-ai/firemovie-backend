from django import forms
from django.contrib import admin

from .models import Article


class ArticleAdminForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = '__all__'
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 32,
                'style': 'font-family: monospace; width: 100%;',
                'spellcheck': 'false',
            }),
        }


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    form = ArticleAdminForm
    list_display = ('title', 'published', 'published_at', 'updated_at')
    list_filter = ('published',)
    search_fields = ('title',)
    list_editable = ('published',)
    readonly_fields = ('slug', 'created_at', 'updated_at')
    fields = ('title', 'cover', 'body', 'published', 'published_at', 'slug', 'created_at', 'updated_at')
