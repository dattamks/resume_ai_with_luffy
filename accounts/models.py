from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class UserProfile(models.Model):
    """
    Extended user profile — one-to-one with Django's User model.
    Stores phone info and other profile fields beyond auth basics.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
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


# ── Signals — auto-create profile + notification prefs on user creation ────

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile and NotificationPreference when a new User is created."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
        NotificationPreference.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Ensure profile is saved whenever user is saved."""
    if hasattr(instance, 'profile'):
        instance.profile.save()
