from django.contrib import admin
from .models import (
    UserProfile, NotificationPreference, EmailTemplate, Plan,
    Wallet, WalletTransaction, CreditCost,
    RazorpayPayment, RazorpaySubscription,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'plan_valid_until', 'pending_plan', 'country_code', 'mobile_number')
    list_filter = ('plan',)
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


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'slug', 'billing_cycle', 'price',
        'credits_per_month', 'max_credits_balance',
        'topup_credits_per_pack', 'topup_price',
        'analyses_per_month', 'api_rate_per_hour',
        'is_active', 'display_order',
    )
    list_filter = ('billing_cycle', 'is_active')
    search_fields = ('name', 'slug')
    readonly_fields = ('created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'billing_cycle', 'price', 'is_active', 'display_order'),
        }),
        ('Credits & Wallet', {
            'fields': ('credits_per_month', 'max_credits_balance', 'topup_credits_per_pack', 'topup_price'),
        }),
        ('Quotas & Limits', {
            'fields': ('analyses_per_month', 'api_rate_per_hour', 'max_resume_size_mb', 'max_resumes_stored'),
        }),
        ('Feature Flags', {
            'fields': ('job_notifications', 'max_job_alerts', 'pdf_export', 'share_analysis', 'job_tracking', 'priority_queue', 'email_support'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'updated_at')
    search_fields = ('user__username',)
    raw_id_fields = ('user',)
    readonly_fields = ('user', 'balance', 'updated_at')


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'amount', 'balance_after', 'transaction_type', 'description', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('wallet__user__username', 'description', 'reference_id')
    readonly_fields = ('wallet', 'amount', 'balance_after', 'transaction_type', 'description', 'reference_id', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # Transactions are created by the system only

    def has_change_permission(self, request, obj=None):
        return False  # Transactions are immutable

    def has_delete_permission(self, request, obj=None):
        return False  # Transactions are immutable


@admin.register(CreditCost)
class CreditCostAdmin(admin.ModelAdmin):
    list_display = ('action', 'cost', 'description')
    search_fields = ('action',)


@admin.register(RazorpayPayment)
class RazorpayPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'payment_type', 'razorpay_order_id', 'razorpay_payment_id',
        'amount', 'status', 'credits_granted', 'webhook_verified', 'created_at',
    )
    list_filter = ('payment_type', 'status', 'credits_granted', 'webhook_verified')
    search_fields = ('user__username', 'razorpay_order_id', 'razorpay_payment_id', 'razorpay_subscription_id')
    raw_id_fields = ('user',)
    readonly_fields = (
        'user', 'payment_type', 'razorpay_order_id', 'razorpay_payment_id',
        'razorpay_signature', 'razorpay_subscription_id', 'amount', 'currency',
        'status', 'notes', 'webhook_verified', 'credits_granted', 'created_at', 'updated_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RazorpaySubscription)
class RazorpaySubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'plan', 'razorpay_subscription_id', 'status',
        'current_start', 'current_end', 'created_at',
    )
    list_filter = ('status', 'plan')
    search_fields = ('user__username', 'razorpay_subscription_id')
    raw_id_fields = ('user',)
    readonly_fields = (
        'user', 'plan', 'razorpay_subscription_id', 'razorpay_plan_id',
        'status', 'current_start', 'current_end', 'short_url',
        'created_at', 'updated_at',
    )
