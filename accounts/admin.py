from django.contrib import admin
from django.contrib import messages
from .models import (
    UserProfile, NotificationPreference, EmailTemplate, Plan,
    Wallet, WalletTransaction, CreditCost,
    RazorpayPayment, RazorpaySubscription, WebhookEvent,
    ConsentLog,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'plan', 'plan_valid_until', 'pending_plan',
        'country_code', 'mobile_number',
        'agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in',
    )
    list_filter = ('plan', 'agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in')
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
        'name', 'slug', 'billing_cycle', 'price', 'original_price',
        'credits_per_month', 'max_credits_balance',
        'topup_credits_per_pack', 'topup_price',
        'analyses_per_month', 'api_rate_per_hour',
        'razorpay_plan_id',
        'is_active', 'display_order',
    )
    list_filter = ('billing_cycle', 'is_active')
    search_fields = ('name', 'slug', 'razorpay_plan_id')
    readonly_fields = ('razorpay_plan_id', 'created_at', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    actions = ['duplicate_plans', 'sync_with_razorpay', 'deactivate_plans', 'activate_plans']
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'description', 'billing_cycle', 'price', 'original_price', 'is_active', 'display_order'),
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
        ('Razorpay', {
            'fields': ('razorpay_plan_id',),
            'description': 'Managed automatically. A new Razorpay plan is created via API when price or billing cycle changes.',
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def has_delete_permission(self, request, obj=None):
        """Plans should never be deleted — deactivate instead (audit trail)."""
        return False

    def save_model(self, request, obj, form, change):
        """
        On save: if price or billing_cycle changed on a paid plan,
        auto-create a new Razorpay plan via API.
        """
        price_changed = False
        billing_changed = False

        if change and obj.pk:
            try:
                old = Plan.objects.get(pk=obj.pk)
                price_changed = old.price != obj.price
                billing_changed = old.billing_cycle != obj.billing_cycle
            except Plan.DoesNotExist:
                pass

        super().save_model(request, obj, form, change)

        # Auto-sync with Razorpay if pricing changed on a paid plan
        if obj.price > 0 and (price_changed or billing_changed):
            try:
                from .razorpay_service import sync_razorpay_plan
                old_id = obj.razorpay_plan_id
                new_id = sync_razorpay_plan(obj, force=True)
                messages.success(
                    request,
                    f'Razorpay plan synced: {new_id} '
                    f'(previous: {old_id or "none"}). '
                    f'Existing subscribers stay on the old price until they re-subscribe.',
                )
            except Exception as e:
                messages.warning(
                    request,
                    f'Plan saved but Razorpay sync failed: {e}. '
                    f'You can retry via Actions → "Sync with Razorpay".',
                )

    @admin.action(description='📋 Duplicate selected plans')
    def duplicate_plans(self, request, queryset):
        """Create a copy of selected plans with a new name/slug."""
        created = 0
        for plan in queryset:
            # Find a unique name/slug
            base_name = plan.name
            base_slug = plan.slug
            counter = 1
            while Plan.objects.filter(slug=f'{base_slug}-copy-{counter}').exists():
                counter += 1

            plan.pk = None  # Django trick: setting pk=None creates a new row on save
            plan.name = f'{base_name} (Copy {counter})'
            plan.slug = f'{base_slug}-copy-{counter}'
            plan.razorpay_plan_id = ''  # New plan needs its own Razorpay plan
            plan.is_active = False  # Start deactivated so admin can review
            plan.save()
            created += 1

        messages.success(request, f'{created} plan(s) duplicated. They are deactivated — review and activate when ready.')
    duplicate_plans.short_description = '📋 Duplicate selected plans'

    @admin.action(description='🔄 Sync with Razorpay')
    def sync_with_razorpay(self, request, queryset):
        """Create/update Razorpay plans for selected paid plans."""
        from .razorpay_service import sync_razorpay_plan

        synced = 0
        for plan in queryset:
            if plan.price == 0:
                messages.info(request, f'Skipped "{plan.name}" — free plans don\'t need Razorpay sync.')
                continue
            try:
                new_id = sync_razorpay_plan(plan, force=True)
                messages.success(request, f'"{plan.name}" synced → {new_id}')
                synced += 1
            except Exception as e:
                messages.error(request, f'Failed to sync "{plan.name}": {e}')

        if synced:
            messages.success(request, f'{synced} plan(s) synced with Razorpay.')
    sync_with_razorpay.short_description = '🔄 Sync with Razorpay'

    @admin.action(description='🔴 Deactivate selected plans')
    def deactivate_plans(self, request, queryset):
        count = queryset.update(is_active=False)
        messages.success(request, f'{count} plan(s) deactivated. Existing subscribers are unaffected.')
    deactivate_plans.short_description = '🔴 Deactivate selected plans'

    @admin.action(description='🟢 Activate selected plans')
    def activate_plans(self, request, queryset):
        count = queryset.update(is_active=True)
        messages.success(request, f'{count} plan(s) activated.')
    activate_plans.short_description = '🟢 Activate selected plans'


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


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'event_type', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('event_id',)
    readonly_fields = ('event_id', 'event_type', 'created_at')
    list_per_page = 50


@admin.register(ConsentLog)
class ConsentLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'consent_type', 'agreed', 'version', 'ip_address', 'created_at')
    list_filter = ('consent_type', 'agreed', 'version')
    search_fields = ('user__username', 'user__email', 'ip_address')
    raw_id_fields = ('user',)
    readonly_fields = ('user', 'consent_type', 'agreed', 'version', 'ip_address', 'user_agent', 'created_at')
    ordering = ('-created_at',)
    list_per_page = 50

    def has_add_permission(self, request):
        return False  # Consent logs are created by the system only

    def has_change_permission(self, request, obj=None):
        return False  # Consent logs are immutable

    def has_delete_permission(self, request, obj=None):
        return False  # Consent logs are immutable
