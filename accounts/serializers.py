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
            'analyses_per_month', 'api_rate_per_hour',
            'max_resume_size_mb', 'max_resumes_stored',
            'credits_per_month', 'max_credits_balance',
            'topup_credits_per_pack', 'topup_price',
            'job_notifications',
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
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password2')

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
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

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'date_joined',
            'country_code', 'mobile_number',
            'plan', 'wallet', 'plan_valid_until', 'pending_plan',
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

    class Meta:
        model = User
        fields = ('username', 'email', 'country_code', 'mobile_number')

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
        if value and not value.startswith('+'):
            raise serializers.ValidationError('Country code must start with + (e.g., +91).')
        return value

    def validate_mobile_number(self, value):
        if value and not value.isdigit():
            raise serializers.ValidationError('Mobile number must contain only digits.')
        return value

    def update(self, instance, validated_data):
        # Extract profile fields before passing to User update
        country_code = validated_data.pop('country_code', None)
        mobile_number = validated_data.pop('mobile_number', None)

        # Update User fields (username, email)
        instance = super().update(instance, validated_data)

        # Update profile fields if provided
        if country_code is not None or mobile_number is not None:
            profile = instance.profile
            if country_code is not None:
                profile.country_code = country_code
            if mobile_number is not None:
                profile.mobile_number = mobile_number
            profile.save(update_fields=['country_code', 'mobile_number'])

        return instance


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
