from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import UserProfile, NotificationPreference, Plan, Wallet, WalletTransaction


class PlanSerializer(serializers.ModelSerializer):
    """Read-only serializer for plan details exposed in user profile."""

    class Meta:
        model = Plan
        fields = (
            'id', 'name', 'slug', 'description', 'billing_cycle', 'price',
            'original_price',
            'analyses_per_month', 'api_rate_per_hour',
            'max_resume_size_mb', 'max_resumes_stored',
            'credits_per_month', 'max_credits_balance',
            'topup_credits_per_pack', 'topup_price',
            'job_notifications', 'max_job_alerts',
            'pdf_export', 'share_analysis', 'job_tracking',
            'priority_queue', 'email_support',
        )
        read_only_fields = fields


class WalletSerializer(serializers.ModelSerializer):
    """Read-only serializer for wallet balance."""

    class Meta:
        model = Wallet
        fields = ('balance', 'updated_at')
        read_only_fields = fields


class WalletTransactionSerializer(serializers.ModelSerializer):
    """Read-only serializer for wallet transaction history."""

    class Meta:
        model = WalletTransaction
        fields = (
            'id', 'amount', 'balance_after', 'transaction_type',
            'description', 'reference_id', 'created_at',
        )
        read_only_fields = fields


class UserProfileSerializer(serializers.ModelSerializer):
    """Read/write serializer for the UserProfile model."""

    class Meta:
        model = UserProfile
        fields = ('country_code', 'mobile_number')


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """Read/write serializer for notification preferences."""

    class Meta:
        model = NotificationPreference
        fields = (
            'job_alerts_email', 'job_alerts_mobile',
            'feature_updates_email', 'feature_updates_mobile',
            'newsletters_email', 'newsletters_mobile',
            'policy_changes_email', 'policy_changes_mobile',
        )


class RegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        required=True,
        help_text='Required. Used for password reset and notifications.',
    )
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    # ── Consent checkboxes ─────────────────────────────────────────────────────
    agree_to_terms = serializers.BooleanField(
        write_only=True,
        help_text='Must be true. User agrees to Terms of Service and Privacy Policy.',
    )
    agree_to_data_usage = serializers.BooleanField(
        write_only=True,
        help_text='Must be true. User acknowledges AI data processing and Data Usage Policy.',
    )
    marketing_opt_in = serializers.BooleanField(
        write_only=True, required=False, default=False,
        help_text='Optional. User opts in to marketing emails and newsletters.',
    )

    class Meta:
        model = User
        fields = (
            'username', 'email', 'password', 'password2',
            'agree_to_terms', 'agree_to_data_usage', 'marketing_opt_in',
        )

    def validate_email(self, value):
        value = value.lower().strip()
        if not value:
            raise serializers.ValidationError('Email is required.')
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        if not attrs.get('agree_to_terms'):
            raise serializers.ValidationError({
                'agree_to_terms': 'You must agree to the Terms of Service and Privacy Policy.',
            })
        if not attrs.get('agree_to_data_usage'):
            raise serializers.ValidationError({
                'agree_to_data_usage': 'You must acknowledge the Data Usage & AI Disclaimer.',
            })
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        validated_data.pop('agree_to_terms')
        validated_data.pop('agree_to_data_usage')
        validated_data.pop('marketing_opt_in', None)
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    """Read-only serializer for user info + profile (phone) fields."""
    country_code = serializers.CharField(source='profile.country_code', read_only=True)
    mobile_number = serializers.CharField(source='profile.mobile_number', read_only=True)
    plan = serializers.SerializerMethodField()
    wallet = serializers.SerializerMethodField()
    plan_valid_until = serializers.DateTimeField(source='profile.plan_valid_until', read_only=True)
    pending_plan = serializers.SerializerMethodField()
    agreed_to_terms = serializers.BooleanField(source='profile.agreed_to_terms', read_only=True)
    agreed_to_data_usage = serializers.BooleanField(source='profile.agreed_to_data_usage', read_only=True)
    marketing_opt_in = serializers.BooleanField(source='profile.marketing_opt_in', read_only=True)
    auth_provider = serializers.CharField(source='profile.auth_provider', read_only=True)
    avatar_url = serializers.URLField(source='profile.avatar_url', read_only=True)
    website_url = serializers.URLField(source='profile.website_url', read_only=True)
    github_url = serializers.URLField(source='profile.github_url', read_only=True)
    linkedin_url = serializers.URLField(source='profile.linkedin_url', read_only=True)

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'date_joined',
            'country_code', 'mobile_number',
            'plan', 'wallet', 'plan_valid_until', 'pending_plan',
            'agreed_to_terms', 'agreed_to_data_usage', 'marketing_opt_in',
            'auth_provider', 'avatar_url',
            'website_url', 'github_url', 'linkedin_url',
        )

    def get_plan(self, obj):
        """Return plan details or None if no plan assigned."""
        profile = getattr(obj, 'profile', None)
        if profile and profile.plan:
            return PlanSerializer(profile.plan).data
        return None

    def get_wallet(self, obj):
        """Return wallet balance or None."""
        wallet = getattr(obj, 'wallet', None)
        if wallet:
            return WalletSerializer(wallet).data
        return None

    def get_pending_plan(self, obj):
        """Return pending plan details or None."""
        profile = getattr(obj, 'profile', None)
        if profile and profile.pending_plan:
            return PlanSerializer(profile.pending_plan).data
        return None


class UpdateUserSerializer(serializers.ModelSerializer):
    """Writable serializer for updating username, email, and phone fields."""
    country_code = serializers.CharField(
        required=False,
        max_length=5,
        help_text='Phone country code with + prefix (e.g., +91, +1, +44)',
    )
    mobile_number = serializers.CharField(
        required=False,
        max_length=15,
        allow_blank=True,
        help_text='Mobile number without country code',
    )
    website_url = serializers.URLField(
        required=False,
        max_length=300,
        allow_blank=True,
        help_text='Personal website or portfolio URL',
    )
    github_url = serializers.URLField(
        required=False,
        max_length=300,
        allow_blank=True,
        help_text='GitHub profile URL',
    )
    linkedin_url = serializers.URLField(
        required=False,
        max_length=300,
        allow_blank=True,
        help_text='LinkedIn profile URL',
    )
    avatar_url = serializers.URLField(
        required=False,
        max_length=500,
        allow_blank=True,
        help_text='Profile picture URL',
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'country_code', 'mobile_number',
                  'website_url', 'github_url', 'linkedin_url', 'avatar_url')

    def validate_username(self, value):
        user = self.context['request'].user
        if User.objects.filter(username=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('This username is already taken.')
        return value

    def validate_email(self, value):
        user = self.context['request'].user
        if value and User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError('This email is already in use.')
        return value

    def validate_country_code(self, value):
        import re
        if value and not re.match(r'^\+\d{1,4}$', value):
            raise serializers.ValidationError(
                'Country code must be + followed by 1–4 digits (e.g., +91, +1, +44).'
            )
        return value

    def validate_mobile_number(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('Mobile number must contain only digits.')
        if value and len(value) < 7:
            raise serializers.ValidationError('Mobile number must be at least 7 digits.')
        return value

    def update(self, instance, validated_data):
        # Extract profile fields before passing to User update
        country_code = validated_data.pop('country_code', None)
        mobile_number = validated_data.pop('mobile_number', None)
        website_url = validated_data.pop('website_url', None)
        github_url = validated_data.pop('github_url', None)
        linkedin_url = validated_data.pop('linkedin_url', None)
        avatar_url = validated_data.pop('avatar_url', None)

        # Update User fields (username, email, first_name, last_name)
        instance = super().update(instance, validated_data)

        # Update profile fields if provided
        profile = instance.profile
        update_fields = []
        profile_updates = {
            'country_code': country_code,
            'mobile_number': mobile_number,
            'website_url': website_url,
            'github_url': github_url,
            'linkedin_url': linkedin_url,
            'avatar_url': avatar_url,
        }
        for field_name, value in profile_updates.items():
            if value is not None:
                setattr(profile, field_name, value)
                update_fields.append(field_name)

        if update_fields:
            profile.save(update_fields=update_fields)

        return instance


class DeleteAccountSerializer(serializers.Serializer):
    """Requires password confirmation before account deletion."""
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Password is incorrect.')
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """Validates current password and sets a new one."""
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """Accepts an email and triggers a password reset email."""
    email = serializers.EmailField()

    def validate_email(self, value):
        # Always return success (don't reveal whether email exists)
        return value.lower().strip()


class ResetPasswordSerializer(serializers.Serializer):
    """Validates the reset token and sets a new password."""
    uid = serializers.CharField(help_text='Base64-encoded user ID from the reset link')
    token = serializers.CharField(help_text='Password reset token from the reset link')
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate(self, attrs):
        try:
            uid = urlsafe_base64_decode(attrs['uid']).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({'uid': 'Invalid or expired reset link.'})

        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({'token': 'Invalid or expired reset token.'})

        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = UserSerializer(self.user).data
        return data


# ── Razorpay Payment Serializers ────────────────────────────────────────────

class CreateSubscriptionSerializer(serializers.Serializer):
    """Input for creating a Razorpay subscription."""
    plan_slug = serializers.SlugField(
        max_length=50,
        help_text='Slug of the plan to subscribe to (e.g., "pro").',
    )


class VerifySubscriptionSerializer(serializers.Serializer):
    """Input for verifying a Razorpay subscription payment."""
    razorpay_subscription_id = serializers.CharField(
        max_length=100,
        help_text='Razorpay subscription ID from checkout response.',
    )
    razorpay_payment_id = serializers.CharField(
        max_length=100,
        help_text='Razorpay payment ID from checkout response.',
    )
    razorpay_signature = serializers.CharField(
        max_length=255,
        help_text='Razorpay signature from checkout response.',
    )


class CreateTopUpOrderSerializer(serializers.Serializer):
    """Input for creating a top-up order."""
    quantity = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=50,
        help_text='Number of credit packs to buy (default: 1).',
    )


class VerifyTopUpSerializer(serializers.Serializer):
    """Input for verifying a top-up payment."""
    razorpay_order_id = serializers.CharField(
        max_length=100,
        help_text='Razorpay order ID from checkout response.',
    )
    razorpay_payment_id = serializers.CharField(
        max_length=100,
        help_text='Razorpay payment ID from checkout response.',
    )
    razorpay_signature = serializers.CharField(
        max_length=255,
        help_text='Razorpay signature from checkout response.',
    )


class PaymentHistorySerializer(serializers.Serializer):
    """Read-only serializer for payment history entries."""
    id = serializers.IntegerField()
    payment_type = serializers.CharField()
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    amount = serializers.IntegerField()
    amount_display = serializers.CharField()
    currency = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.CharField()


class SubscriptionStatusSerializer(serializers.Serializer):
    """Read-only serializer for subscription status."""
    has_subscription = serializers.BooleanField()
    subscription_id = serializers.CharField(required=False)
    plan = serializers.CharField(required=False)
    plan_name = serializers.CharField(required=False)
    status = serializers.CharField(required=False, allow_null=True)
    is_active = serializers.BooleanField()
    current_start = serializers.DateTimeField(required=False, allow_null=True)
    current_end = serializers.DateTimeField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(required=False, allow_null=True)


# ── Google OAuth Serializers ────────────────────────────────────────────────

class GoogleAuthSerializer(serializers.Serializer):
    """Input for Google OAuth login — receives the Google ID token from frontend."""
    token = serializers.CharField(
        help_text='Google ID token (credential) from Google Sign-In / One Tap.',
    )


class GoogleCompleteSerializer(serializers.Serializer):
    """Input for completing Google sign-up — username, password, and consent checkboxes."""
    temp_token = serializers.CharField(
        help_text='Temporary token received from POST /api/auth/google/.',
    )
    username = serializers.CharField(
        max_length=150,
        help_text='Chosen username for the new account.',
    )
    password = serializers.CharField(
        write_only=True,
        validators=[validate_password],
        help_text='Password for the new account (min 8 chars, not too common/numeric).',
    )
    agree_to_terms = serializers.BooleanField(
        help_text='Must be true. User agrees to Terms of Service and Privacy Policy.',
    )
    agree_to_data_usage = serializers.BooleanField(
        help_text='Must be true. User acknowledges AI data processing and Data Usage Policy.',
    )
    marketing_opt_in = serializers.BooleanField(
        required=False, default=False,
        help_text='Optional. User opts in to marketing emails and newsletters.',
    )

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError('A user with that username already exists.')
        return value

    def validate(self, attrs):
        if not attrs.get('agree_to_terms'):
            raise serializers.ValidationError({
                'agree_to_terms': 'You must agree to the Terms of Service and Privacy Policy.',
            })
        if not attrs.get('agree_to_data_usage'):
            raise serializers.ValidationError({
                'agree_to_data_usage': 'You must acknowledge the Data Usage & AI Disclaimer.',
            })
        return attrs
