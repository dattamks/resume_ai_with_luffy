import logging

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger('accounts')


class UserProfile(models.Model):
    """
    Extended user profile — one-to-one with Django's User model.
    Stores phone info, plan assignment, and other profile fields beyond auth basics.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    plan = models.ForeignKey(
        'Plan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text='Current subscription plan. NULL = Free tier defaults.',
    )
    country_code = models.CharField(
        max_length=5,
        default='+91',
        help_text='Phone country code with + prefix (e.g., +91, +1, +44)',
    )
    mobile_number = models.CharField(
        max_length=15,
        blank=True,
        help_text='Mobile number without country code',
    )
    plan_valid_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the current billing cycle ends. NULL for free plans.',
    )
    pending_plan = models.ForeignKey(
        'Plan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pending_users',
        help_text='Plan to switch to after current billing cycle expires (for downgrades).',
    )

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'

    def __str__(self):
        return f"Profile({self.user.username})"


class NotificationPreference(models.Model):
    """
    Per-user notification preferences.
    Each notification type has an email and mobile/SMS toggle.
    Created automatically when a UserProfile is created.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')

    # Job Alerts — new matching jobs found
    job_alerts_email = models.BooleanField(default=True)
    job_alerts_mobile = models.BooleanField(default=False)

    # Feature Updates — new features, improvements
    feature_updates_email = models.BooleanField(default=True)
    feature_updates_mobile = models.BooleanField(default=False)

    # Newsletters — periodic roundups, tips
    newsletters_email = models.BooleanField(default=True)
    newsletters_mobile = models.BooleanField(default=False)

    # Policy & Terms Changes — legal updates, ToS changes
    policy_changes_email = models.BooleanField(default=True)
    policy_changes_mobile = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'

    def __str__(self):
        return f"NotificationPrefs({self.user.username})"


class EmailTemplate(models.Model):
    """
    Stores reusable email templates with HTML body and plain-text fallback.
    Templates support Django template syntax for variable substitution:
        {{ username }}, {{ reset_link }}, {{ app_name }}, etc.
    """
    CATEGORY_CHOICES = [
        ('auth', 'Authentication'),
        ('notification', 'Notification'),
        ('marketing', 'Marketing'),
        ('system', 'System'),
    ]

    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text='Unique identifier used in code to look up this template (e.g., "password-reset").',
    )
    name = models.CharField(
        max_length=200,
        help_text='Human-readable template name (for admin display).',
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='system',
        help_text='Template category for filtering in admin.',
    )
    subject = models.CharField(
        max_length=255,
        help_text='Email subject line. Supports Django template variables (e.g., "{{ app_name }} — Password Reset").',
    )
    html_body = models.TextField(
        help_text='HTML email body. Use Django template syntax for variables: {{ username }}, {{ reset_link }}, etc.',
    )
    plain_text_body = models.TextField(
        blank=True,
        help_text='Plain-text fallback (auto-generated from HTML if left blank).',
    )
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text='Internal note explaining when this template is used.',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Inactive templates cannot be sent.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Email Template'
        verbose_name_plural = 'Email Templates'
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.slug})"


class Plan(models.Model):
    """
    Subscription/plan tiers for the platform.
    Assigned to users via UserProfile.plan FK — admin-managed for now,
    future wallet/Stripe integration will automate upgrades.
    """
    BILLING_CHOICES = [
        ('free', 'Free'),
        ('monthly', 'Monthly'),
        ('yearly', 'Yearly'),
        ('lifetime', 'Lifetime'),
    ]

    name = models.CharField(
        max_length=50,
        unique=True,
        help_text='Plan display name (e.g., "Free", "Pro", "Enterprise").',
    )
    slug = models.SlugField(
        max_length=50,
        unique=True,
        help_text='Plan identifier used in code (e.g., "free", "pro").',
    )
    description = models.CharField(
        max_length=500,
        blank=True,
        help_text='Short description shown to users.',
    )
    billing_cycle = models.CharField(
        max_length=10,
        choices=BILLING_CHOICES,
        default='free',
    )
    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text='Price in INR (0 for free tier).',
    )

    # ── Quotas & Limits ──────────────────────────────────────────────────
    analyses_per_month = models.IntegerField(
        default=0,
        help_text='Max analyses per month (0 = unlimited).',
    )
    api_rate_per_hour = models.IntegerField(
        default=200,
        help_text='Max general API requests per hour.',
    )
    max_resume_size_mb = models.IntegerField(
        default=5,
        help_text='Max resume file size in MB.',
    )
    max_resumes_stored = models.IntegerField(
        default=5,
        help_text='Max resumes stored at once (0 = unlimited).',
    )

    # ── Credits & Wallet ──────────────────────────────────────────────
    credits_per_month = models.PositiveIntegerField(
        default=0,
        help_text='Credits granted each billing cycle (0 = none).',
    )
    max_credits_balance = models.PositiveIntegerField(
        default=0,
        help_text='Max credits from monthly grants (0 = no cap). Top-ups bypass this cap.',
    )
    topup_credits_per_pack = models.PositiveIntegerField(
        default=0,
        help_text='Credits per top-up pack (0 = top-up not allowed for this plan).',
    )
    topup_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text='Price per top-up pack in INR.',
    )

    # ── Feature Flags ────────────────────────────────────────────────────
    job_notifications = models.BooleanField(
        default=False,
        help_text='Can receive job alert notifications.',
    )
    max_job_alerts = models.PositiveSmallIntegerField(
        default=0,
        help_text='Max active job alerts allowed (0 = not permitted, Pro = 3).',
    )
    pdf_export = models.BooleanField(
        default=True,
        help_text='Can export analysis as PDF report.',
    )
    share_analysis = models.BooleanField(
        default=True,
        help_text='Can generate public share links.',
    )
    job_tracking = models.BooleanField(
        default=True,
        help_text='Can use job tracking features.',
    )
    priority_queue = models.BooleanField(
        default=False,
        help_text='Analyses processed in priority Celery queue.',
    )
    email_support = models.BooleanField(
        default=False,
        help_text='Has access to email support.',
    )

    is_active = models.BooleanField(
        default=True,
        help_text='Inactive plans cannot be assigned to new users.',
    )
    display_order = models.IntegerField(
        default=0,
        help_text='Sort order on pricing page (lower = first).',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plan'
        verbose_name_plural = 'Plans'
        ordering = ['display_order', 'price']

    def __str__(self):
        return f"{self.name} (₹{self.price}/{self.billing_cycle})"


class Wallet(models.Model):
    """
    Per-user credit wallet. OneToOne with User.
    Balance is always >= 0; enforced at the service layer with select_for_update().
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.PositiveIntegerField(
        default=0,
        help_text='Current credit balance.',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'

    def __str__(self):
        return f"Wallet({self.user.username}, balance={self.balance})"


class WalletTransaction(models.Model):
    """
    Immutable audit log for every credit change.
    Append-only — never update or delete rows.
    """
    TYPE_PLAN_CREDIT = 'plan_credit'
    TYPE_TOPUP = 'topup'
    TYPE_ANALYSIS_DEBIT = 'analysis_debit'
    TYPE_REFUND = 'refund'
    TYPE_ADMIN_ADJUSTMENT = 'admin_adjustment'
    TYPE_UPGRADE_BONUS = 'upgrade_bonus'
    TYPE_CHOICES = [
        (TYPE_PLAN_CREDIT, 'Monthly Plan Credit'),
        (TYPE_TOPUP, 'Top-Up Purchase'),
        (TYPE_ANALYSIS_DEBIT, 'Analysis Debit'),
        (TYPE_REFUND, 'Refund'),
        (TYPE_ADMIN_ADJUSTMENT, 'Admin Adjustment'),
        (TYPE_UPGRADE_BONUS, 'Upgrade Bonus'),
    ]

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.IntegerField(
        help_text='Positive = credit, negative = debit.',
    )
    balance_after = models.PositiveIntegerField(
        help_text='Wallet balance after this transaction.',
    )
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    description = models.CharField(max_length=255)
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        help_text='Links to analysis ID or other context.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Wallet Transaction'
        verbose_name_plural = 'Wallet Transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['wallet', '-created_at']),
            models.Index(fields=['transaction_type', '-created_at']),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f"{sign}{self.amount} ({self.transaction_type}) → {self.balance_after}"


class CreditCost(models.Model):
    """
    Admin-managed credit costs per action.
    Allows changing analysis cost without code deploys.
    """
    action = models.SlugField(
        max_length=50,
        unique=True,
        help_text='Action identifier (e.g., "resume_analysis").',
    )
    cost = models.PositiveIntegerField(
        default=1,
        help_text='Credits consumed per action.',
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text='Human-readable description of this action.',
    )

    class Meta:
        verbose_name = 'Credit Cost'
        verbose_name_plural = 'Credit Costs'

    def __str__(self):
        return f"{self.action} = {self.cost} credits"


# ── Signals — auto-create profile + notification prefs + wallet on user creation ──

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile, NotificationPreference, and Wallet when a new User is created."""
    if created:
        # Assign the default 'free' plan if it exists
        free_plan = Plan.objects.filter(slug='free', is_active=True).first()
        UserProfile.objects.get_or_create(user=instance, defaults={'plan': free_plan})
        NotificationPreference.objects.get_or_create(user=instance)

        # Create wallet with initial plan credits
        initial_credits = free_plan.credits_per_month if free_plan else 0
        wallet, wallet_created = Wallet.objects.get_or_create(
            user=instance, defaults={'balance': initial_credits}
        )
        if wallet_created and initial_credits > 0:
            WalletTransaction.objects.create(
                wallet=wallet,
                amount=initial_credits,
                balance_after=initial_credits,
                transaction_type=WalletTransaction.TYPE_PLAN_CREDIT,
                description=f'Initial {free_plan.name} plan credits',
            )
            logger.info('Wallet created for user=%s with %d credits', instance.username, initial_credits)
