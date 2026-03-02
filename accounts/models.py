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

    # ── Consent quick-access flags ─────────────────────────────────────
    agreed_to_terms = models.BooleanField(
        default=True,
        help_text='User agreed to Terms of Service and Privacy Policy.',
    )
    agreed_to_data_usage = models.BooleanField(
        default=True,
        help_text='User acknowledged AI data processing and Data Usage Policy.',
    )
    marketing_opt_in = models.BooleanField(
        default=False,
        help_text='User opted in to marketing emails, tips, and newsletters.',
    )

    # ── Google / Social profile fields ─────────────────────────────────
    AUTH_PROVIDER_CHOICES = [
        ('email', 'Email'),
        ('google', 'Google'),
    ]
    auth_provider = models.CharField(
        max_length=20,
        choices=AUTH_PROVIDER_CHOICES,
        default='email',
        help_text='How the user signed up (email registration or Google OAuth).',
    )
    avatar_url = models.URLField(
        max_length=500,
        blank=True,
        default='',
        help_text='Profile picture URL (from Google or uploaded). Blank means no avatar.',
    )
    google_sub = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Google account unique subject identifier (from ID token).',
    )

    # ── Social links ──────────────────────────────────────────────────────
    website_url = models.URLField(
        max_length=300,
        blank=True,
        default='',
        help_text='Personal website or portfolio URL.',
    )
    github_url = models.URLField(
        max_length=300,
        blank=True,
        default='',
        help_text='GitHub profile URL.',
    )
    linkedin_url = models.URLField(
        max_length=300,
        blank=True,
        default='',
        help_text='LinkedIn profile URL.',
    )

    # ── Geography ──────────────────────────────────────────────────────────
    country = models.CharField(
        max_length=100,
        default='India',
        help_text='Country of residence. Used as primary geo filter for feed & analytics.',
    )
    state = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='State / province / region (e.g. "Karnataka", "California").',
    )
    city = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='City of residence (e.g. "Bangalore", "Mumbai").',
    )

    # ── Email verification ──────────────────────────────────────────────────
    is_email_verified = models.BooleanField(
        default=False,
        help_text='True after user clicks the email verification link. Google OAuth users are auto-verified.',
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
        help_text='Discounted/current price in INR (what users actually pay).',
    )
    original_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0,
        help_text='Original price in INR before discount (0 = no discount). Shown as strikethrough on frontend.',
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
        help_text='Maximum number of job alerts allowed. 0 = no access. Pro plan = 5.',
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
    premium_templates = models.BooleanField(
        default=False,
        help_text='Can use premium resume templates.',
    )

    # ── Razorpay Integration ─────────────────────────────────────────────
    razorpay_plan_id = models.CharField(
        max_length=100,
        blank=True,
        default='',
        help_text='Current Razorpay plan_id. Auto-managed — created via API when price/billing changes.',
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


# ── Razorpay Payment Models ─────────────────────────────────────────────────

class RazorpayPayment(models.Model):
    """
    Tracks every payment attempt through Razorpay (subscriptions & one-time top-ups).
    Serves as the single source of truth for payment verification & idempotency.
    """
    PAYMENT_TYPE_SUBSCRIPTION = 'subscription'
    PAYMENT_TYPE_TOPUP = 'topup'
    PAYMENT_TYPE_CHOICES = [
        (PAYMENT_TYPE_SUBSCRIPTION, 'Subscription'),
        (PAYMENT_TYPE_TOPUP, 'Top-Up'),
    ]

    STATUS_CREATED = 'created'
    STATUS_AUTHORIZED = 'authorized'
    STATUS_CAPTURED = 'captured'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_AUTHORIZED, 'Authorized'),
        (STATUS_CAPTURED, 'Captured'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='razorpay_payments')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPE_CHOICES)

    # Razorpay identifiers
    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text='Razorpay order_id (for one-time top-ups).',
    )
    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        unique=True,
        null=True,
        default=None,
        help_text='Razorpay payment_id (set after payment completes).',
    )
    razorpay_signature = models.CharField(
        max_length=255,
        blank=True,
        help_text='Razorpay signature for verification.',
    )
    razorpay_subscription_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text='Razorpay subscription_id (for subscription payments).',
    )

    # Payment details
    amount = models.PositiveIntegerField(
        help_text='Amount in paise (₹499 = 49900 paise).',
    )
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)

    # Metadata
    notes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional context (plan_slug, quantity, etc.).',
    )
    webhook_verified = models.BooleanField(
        default=False,
        help_text='True if this payment was confirmed via webhook.',
    )
    credits_granted = models.BooleanField(
        default=False,
        help_text='True if credits/plan have been applied for this payment.',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Razorpay Payment'
        verbose_name_plural = 'Razorpay Payments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f"Payment({self.razorpay_payment_id or self.razorpay_order_id}, {self.status}, ₹{self.amount / 100})"


class RazorpaySubscription(models.Model):
    """
    Tracks Razorpay subscriptions for each user.
    ForeignKey — keeps audit trail of all subscriptions (active + historical).
    Only one subscription should be in an active status at a time (enforced in service layer).
    """
    STATUS_CREATED = 'created'
    STATUS_AUTHENTICATED = 'authenticated'
    STATUS_ACTIVE = 'active'
    STATUS_PENDING = 'pending'
    STATUS_HALTED = 'halted'
    STATUS_CANCELLED = 'cancelled'
    STATUS_COMPLETED = 'completed'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_AUTHENTICATED, 'Authenticated'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_HALTED, 'Halted'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='razorpay_subscriptions')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name='razorpay_subscriptions')

    # Razorpay identifiers
    razorpay_subscription_id = models.CharField(
        max_length=100,
        unique=True,
        help_text='Razorpay subscription_id.',
    )
    razorpay_plan_id = models.CharField(
        max_length=100,
        help_text='Razorpay plan_id used to create this subscription.',
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)

    # Billing cycle info
    current_start = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Start of current billing period.',
    )
    current_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text='End of current billing period.',
    )
    short_url = models.URLField(
        blank=True,
        help_text='Short URL for payment (provided by Razorpay).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Razorpay Subscription'
        verbose_name_plural = 'Razorpay Subscriptions'

    def __str__(self):
        return f"Subscription({self.user.username}, {self.plan.slug}, {self.status})"

    @property
    def is_active(self):
        return self.status in (self.STATUS_ACTIVE, self.STATUS_AUTHENTICATED)


# ── Signals — auto-create profile + notification prefs + wallet on user creation ──

@receiver(post_save, sender=Plan)
def auto_sync_plan_to_razorpay(sender, instance, created, **kwargs):
    """
    Auto-create a Razorpay plan whenever a paid Plan is saved without a razorpay_plan_id.
    Runs on both creation and update. Skips free plans, plans that already have an ID,
    and test environments.
    """
    if instance.price <= 0 or instance.razorpay_plan_id:
        return

    # Skip in test mode (manage.py test sets this)
    import sys
    if 'test' in sys.argv:
        return

    # Skip if Razorpay credentials are not configured
    from django.conf import settings
    if not getattr(settings, 'RAZORPAY_KEY_ID', '') or not getattr(settings, 'RAZORPAY_KEY_SECRET', ''):
        return

    try:
        from .razorpay_service import sync_razorpay_plan
        new_id = sync_razorpay_plan(instance)
        logger.info(
            'Razorpay plan auto-synced: plan=%s razorpay_plan_id=%s',
            instance.slug, new_id,
        )
    except Exception as e:
        logger.warning(
            'Razorpay auto-sync failed for plan=%s: %s (sync manually via manage.py sync_razorpay_plans)',
            instance.slug, e,
        )


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


class ConsentLog(models.Model):
    """
    Immutable audit trail for user consent actions.
    Every time a user agrees (or withdraws consent) for a specific type,
    a new row is created — never updated or deleted.
    """
    CONSENT_TERMS_PRIVACY = 'terms_privacy'
    CONSENT_DATA_USAGE_AI = 'data_usage_ai'
    CONSENT_MARKETING = 'marketing_newsletter'

    CONSENT_TYPE_CHOICES = [
        (CONSENT_TERMS_PRIVACY, 'Terms & Privacy Policy'),
        (CONSENT_DATA_USAGE_AI, 'Data Usage & AI Disclaimer'),
        (CONSENT_MARKETING, 'Marketing & Newsletter'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='consent_logs')
    consent_type = models.CharField(max_length=30, choices=CONSENT_TYPE_CHOICES)
    agreed = models.BooleanField(help_text='True = opted in / agreed; False = withdrew consent.')
    version = models.CharField(
        max_length=20, default='1.0',
        help_text='Version of the legal document the user agreed to.',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Consent Log'
        verbose_name_plural = 'Consent Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'consent_type', '-created_at']),
        ]

    def __str__(self):
        action = 'agreed' if self.agreed else 'withdrew'
        return f'{self.user.username} {action} {self.get_consent_type_display()} (v{self.version})'


class EmailVerificationToken(models.Model):
    """
    Short-lived token for email verification.
    Created on registration, consumed when user clicks the verification link.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_verification_tokens')
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp when the token was used to verify email.',
    )
    expires_at = models.DateTimeField(
        help_text='Token expiry time (default 24 hours after creation).',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Email Verification Token'
        verbose_name_plural = 'Email Verification Tokens'

    def __str__(self):
        status = 'used' if self.used_at else 'pending'
        return f'EmailVerification({self.user.username}, {status})'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.used_at and not self.is_expired

    @classmethod
    def create_for_user(cls, user, hours_valid=24):
        """Create a new verification token for a user."""
        import secrets
        token = secrets.token_urlsafe(48)
        return cls.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timezone.timedelta(hours=hours_valid),
        )


class ContactSubmission(models.Model):
    """
    Landing-page contact form submissions.
    Stores enquiries from visitors (no authentication required).
    """
    name = models.CharField(max_length=100)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.subject} — {self.email}'


class WebhookEvent(models.Model):
    """
    Tracks processed webhook event IDs for replay protection.
    Razorpay may deliver the same event multiple times — storing the event_id
    lets us reject duplicates at the application level.
    """
    event_id = models.CharField(max_length=255, unique=True, db_index=True)
    event_type = models.CharField(max_length=100, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event_type} — {self.event_id}'
