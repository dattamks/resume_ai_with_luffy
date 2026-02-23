from django.contrib import admin
from .models import UserProfile, NotificationPreference, EmailTemplate


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'country_code', 'mobile_number')
    search_fields = ('user__username', 'mobile_number')
    raw_id_fields = ('user',)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'job_alerts_email', 'job_alerts_mobile',
        'feature_updates_email', 'feature_updates_mobile',
        'newsletters_email', 'newsletters_mobile',
        'policy_changes_email', 'policy_changes_mobile',
    )
    raw_id_fields = ('user',)


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'category', 'subject', 'is_active', 'updated_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name', 'slug', 'subject')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'category', 'is_active', 'description'),
        }),
        ('Content', {
            'fields': ('subject', 'html_body', 'plain_text_body'),
            'description': 'Use Django template syntax: {{ username }}, {{ reset_link }}, {{ app_name }}, etc.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
