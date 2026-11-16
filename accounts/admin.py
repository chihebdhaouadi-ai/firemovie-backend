from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from takes.reputation import progress_for

from .models import User

# Display names for the keys computed in takes/reputation.py. The definitions
# (targets, rules) live in code; the admin shows each user's standing against them.
ACHIEVEMENT_LABELS = {
    'film_critic': 'Film critic (write 10 reviews)',
    'debater': 'Debater (50 well-argued votes)',
    'local_cinema': 'Local cinema (not tracked yet)',
}
BADGE_LABELS = {
    'well_argued': 'Well argued',
    'changed_my_mind': 'Changed my mind',
    'disagree_but_fair': 'Disagree but fair',
    'top_critic': 'Top critic (weekly top 3)',
    'first_take': 'First take',
}
FRAME_LABELS = {
    'bronze': 'Newcomer (everyone, from level 1)',
    'explorer': 'Explorer (film critic achievement)',
    'debater': 'Debater (debater achievement)',
    'gold': 'Top critic (top critic badge)',
    'legend': 'Legend (local cinema achievement)',
}


def _progress(user):
    """Progression for one user, computed once per instance per request."""
    if user.pk is None:
        return None
    if not hasattr(user, '_progress_cache'):
        user._progress_cache = progress_for(user)
    return user._progress_cache


def _table(items, labels):
    rows = []
    for item in items:
        name = labels.get(item['key'], item['key'])
        if item.get('available') is False:
            status = 'not tracked yet'
        elif item['unlocked']:
            status = 'unlocked'
        else:
            status = 'locked'
        rows.append(format_html(
            '<tr><td>{}</td><td>{} / {}</td><td>{}</td></tr>',
            name, item['current'], item['target'], status,
        ))
    return format_html(
        '<table><thead><tr><th>Item</th><th>Progress</th><th>Status</th></tr></thead>'
        '<tbody>{}</tbody></table>',
        mark_safe(''.join(rows)),
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'email', 'level', 'xp', 'reviews', 'reactions', 'comments',
        'achievements_unlocked', 'frames_unlocked', 'equipped_frame_label',
        'is_active', 'date_joined',
    )
    list_filter = BaseUserAdmin.list_filter + ('equipped_frame',)
    search_fields = BaseUserAdmin.search_fields + ('bio',)
    readonly_fields = ('progression',)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Profile', {'fields': ('bio', 'avatar', 'cover', 'balance', 'equipped_frame')}),
        ('Progression', {'fields': ('progression',)}),
    )

    @admin.display(description='Level')
    def level(self, obj):
        progress = _progress(obj)
        return progress['level'] if progress else '—'

    @admin.display(description='XP')
    def xp(self, obj):
        progress = _progress(obj)
        return progress['xp'] if progress else '—'

    @admin.display(description='Reviews')
    def reviews(self, obj):
        progress = _progress(obj)
        return progress['reviews'] if progress else '—'

    @admin.display(description='Reactions')
    def reactions(self, obj):
        progress = _progress(obj)
        return progress['reactions'] if progress else '—'

    @admin.display(description='Comments')
    def comments(self, obj):
        progress = _progress(obj)
        return progress['comments'] if progress else '—'

    @admin.display(description='Achievements')
    def achievements_unlocked(self, obj):
        progress = _progress(obj)
        if not progress:
            return '—'
        return f"{sum(a['unlocked'] for a in progress['achievements'])}/{len(progress['achievements'])}"

    @admin.display(description='Frames unlocked')
    def frames_unlocked(self, obj):
        progress = _progress(obj)
        if not progress:
            return '—'
        return f"{sum(f['unlocked'] for f in progress['frames'])}/{len(progress['frames'])}"

    @admin.display(description='Equipped frame')
    def equipped_frame_label(self, obj):
        return FRAME_LABELS.get(obj.equipped_frame, obj.equipped_frame).split(' (')[0]

    @admin.display(description='Progression')
    def progression(self, obj):
        progress = _progress(obj)
        if not progress:
            return 'Available after the user is saved.'
        summary = format_html(
            '<p><strong>Level {}</strong> &middot; {} XP &middot; {} to next level '
            '({} into this level)</p>',
            progress['level'], progress['xp'],
            progress['xp_for_next_level'] - progress['xp_into_level'],
            progress['xp_into_level'],
        )
        return format_html(
            '{}<h4>Achievements</h4>{}<h4>Badges</h4>{}<h4>Frames</h4>{}',
            summary,
            _table(progress['achievements'], ACHIEVEMENT_LABELS),
            _table(progress['badges'], BADGE_LABELS),
            _table(progress['frames'], FRAME_LABELS),
        )
