from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


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

    # ── Feature Flags ────────────────────────────────────────────────────
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


# ── Signals — auto-create profile + notification prefs on user creation ────

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile and NotificationPreference when a new User is created."""
    if created:
        # Assign the default 'free' plan if it exists
        free_plan = Plan.objects.filter(slug='free', is_active=True).first()
        UserProfile.objects.get_or_create(user=instance, defaults={'plan': free_plan})
        NotificationPreference.objects.get_or_create(user=instance)
