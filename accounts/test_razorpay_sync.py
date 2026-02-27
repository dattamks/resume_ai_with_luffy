"""
Tests for Razorpay plan sync logic and admin overrides.

Covers:
- sync_razorpay_plan() service function
- _get_razorpay_plan_id() priority logic
- PlanAdmin.save_model() auto-sync on price change
- PlanAdmin duplicate action
- PlanAdmin delete prevention
- sync_razorpay_plans management command
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch, MagicMock

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, RequestFactory, override_settings

from accounts.admin import PlanAdmin
from accounts.models import Plan


class SyncRazorpayPlanTests(TestCase):
    """Tests for accounts.razorpay_service.sync_razorpay_plan()."""

    def setUp(self):
        self.plan = Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly', price=499,
            credits_per_month=25, max_credits_balance=100,
            is_active=True, display_order=10,
        )

    @patch('accounts.razorpay_service._get_client')
    def test_creates_razorpay_plan_and_stores_id(self, mock_client):
        mock_client.return_value.plan.create.return_value = {'id': 'plan_NEW123'}

        from accounts.razorpay_service import sync_razorpay_plan
        result = sync_razorpay_plan(self.plan, force=True)

        self.assertEqual(result, 'plan_NEW123')
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.razorpay_plan_id, 'plan_NEW123')

        # Verify API call shape
        call_args = mock_client.return_value.plan.create.call_args[0][0]
        self.assertEqual(call_args['period'], 'monthly')
        self.assertEqual(call_args['interval'], 1)
        self.assertEqual(call_args['item']['amount'], 49900)
        self.assertIn('Pro', call_args['item']['name'])

    @patch('accounts.razorpay_service._get_client')
    def test_skips_sync_when_id_exists_and_not_forced(self, mock_client):
        self.plan.razorpay_plan_id = 'plan_EXISTING'
        self.plan.save()

        from accounts.razorpay_service import sync_razorpay_plan
        result = sync_razorpay_plan(self.plan, force=False)

        self.assertEqual(result, 'plan_EXISTING')
        mock_client.return_value.plan.create.assert_not_called()

    @patch('accounts.razorpay_service._get_client')
    def test_force_creates_new_plan_even_with_existing_id(self, mock_client):
        self.plan.razorpay_plan_id = 'plan_OLD'
        self.plan.save()
        mock_client.return_value.plan.create.return_value = {'id': 'plan_NEWFORCED'}

        from accounts.razorpay_service import sync_razorpay_plan
        result = sync_razorpay_plan(self.plan, force=True)

        self.assertEqual(result, 'plan_NEWFORCED')
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.razorpay_plan_id, 'plan_NEWFORCED')

    def test_raises_for_free_plan(self):
        free = Plan.objects.create(
            name='Free', slug='free', billing_cycle='free', price=0,
            credits_per_month=2, max_credits_balance=10,
            is_active=True, display_order=0,
        )
        from accounts.razorpay_service import sync_razorpay_plan
        with self.assertRaises(ValueError):
            sync_razorpay_plan(free)

    @patch('accounts.razorpay_service._get_client')
    def test_api_error_raises_valueerror(self, mock_client):
        mock_client.return_value.plan.create.side_effect = Exception('API timeout')

        from accounts.razorpay_service import sync_razorpay_plan
        with self.assertRaises(ValueError) as ctx:
            sync_razorpay_plan(self.plan, force=True)
        self.assertIn('API timeout', str(ctx.exception))

    @patch('accounts.razorpay_service._get_client')
    def test_yearly_plan_period(self, mock_client):
        self.plan.billing_cycle = 'yearly'
        self.plan.price = 4999
        self.plan.save()
        mock_client.return_value.plan.create.return_value = {'id': 'plan_YEARLY1'}

        from accounts.razorpay_service import sync_razorpay_plan
        sync_razorpay_plan(self.plan, force=True)

        call_args = mock_client.return_value.plan.create.call_args[0][0]
        self.assertEqual(call_args['period'], 'yearly')
        self.assertEqual(call_args['item']['amount'], 499900)


class GetRazorpayPlanIdTests(TestCase):
    """Tests for _get_razorpay_plan_id() priority logic."""

    def setUp(self):
        self.plan = Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly', price=499,
            credits_per_month=25, max_credits_balance=100,
            is_active=True, display_order=10,
        )

    def test_returns_model_field_first(self):
        self.plan.razorpay_plan_id = 'plan_FROM_MODEL'
        self.plan.save()

        from accounts.razorpay_service import _get_razorpay_plan_id
        result = _get_razorpay_plan_id(self.plan)
        self.assertEqual(result, 'plan_FROM_MODEL')

    @override_settings(TESTING=True)
    def test_placeholder_in_test_mode(self):
        from accounts.razorpay_service import _get_razorpay_plan_id
        result = _get_razorpay_plan_id(self.plan)
        self.assertIn('plan_pro', result)

    @override_settings(DEBUG=False, TESTING=False)
    def test_raises_in_production_without_id(self):
        from accounts.razorpay_service import _get_razorpay_plan_id
        with self.assertRaises(ValueError):
            _get_razorpay_plan_id(self.plan)


class PlanAdminTests(TestCase):
    """Tests for PlanAdmin overrides."""

    def setUp(self):
        self.factory = RequestFactory()
        self.site = AdminSite()
        self.admin = PlanAdmin(Plan, self.site)

        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='AdminPass123!'
        )
        self.plan = Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly', price=499,
            credits_per_month=25, max_credits_balance=100,
            is_active=True, display_order=10,
        )

    def test_delete_permission_denied(self):
        request = self.factory.get('/')
        request.user = self.superuser
        self.assertFalse(self.admin.has_delete_permission(request, self.plan))

    @patch('accounts.razorpay_service.sync_razorpay_plan')
    def test_save_model_triggers_sync_on_price_change(self, mock_sync):
        mock_sync.return_value = 'plan_SYNCED123'

        request = self.factory.post('/')
        request.user = self.superuser
        # Django messages middleware workaround
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        setattr(request, '_messages', FallbackStorage(request))

        # Simulate price change
        self.plan.price = Decimal('999')
        form = MagicMock()
        self.admin.save_model(request, self.plan, form, change=True)

        mock_sync.assert_called_once_with(self.plan, force=True)

    @patch('accounts.razorpay_service.sync_razorpay_plan')
    def test_save_model_no_sync_when_price_unchanged(self, mock_sync):
        request = self.factory.post('/')
        request.user = self.superuser
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        setattr(request, '_messages', FallbackStorage(request))

        # Save without changing price
        form = MagicMock()
        self.admin.save_model(request, self.plan, form, change=True)

        mock_sync.assert_not_called()

    def test_duplicate_plan_action(self):
        request = self.factory.post('/')
        request.user = self.superuser
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        setattr(request, '_messages', FallbackStorage(request))

        queryset = Plan.objects.filter(pk=self.plan.pk)
        self.admin.duplicate_plans(request, queryset)

        self.assertEqual(Plan.objects.count(), 2)
        copy = Plan.objects.exclude(pk=self.plan.pk).first()
        self.assertIn('Copy', copy.name)
        self.assertIn('copy', copy.slug)
        self.assertFalse(copy.is_active)  # Starts deactivated
        self.assertEqual(copy.razorpay_plan_id, '')  # Needs its own sync
        self.assertEqual(copy.price, self.plan.price)

    def test_duplicate_multiple_times_increments_counter(self):
        request = self.factory.post('/')
        request.user = self.superuser
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, 'session', 'session')
        setattr(request, '_messages', FallbackStorage(request))

        # Each admin action gets a fresh queryset, so simulate that
        self.admin.duplicate_plans(request, Plan.objects.filter(pk=self.plan.pk))
        self.admin.duplicate_plans(request, Plan.objects.filter(pk=self.plan.pk))

        slugs = list(Plan.objects.values_list('slug', flat=True).order_by('slug'))
        self.assertIn('pro-copy-1', slugs)
        self.assertIn('pro-copy-2', slugs)


class SyncRazorpayPlansCommandTests(TestCase):
    """Tests for the sync_razorpay_plans management command."""

    def setUp(self):
        self.free = Plan.objects.create(
            name='Free', slug='free', billing_cycle='free', price=0,
            is_active=True, display_order=0,
        )
        self.pro = Plan.objects.create(
            name='Pro', slug='pro', billing_cycle='monthly', price=499,
            is_active=True, display_order=10,
        )

    @patch('accounts.razorpay_service._get_client')
    def test_syncs_paid_plans_without_razorpay_id(self, mock_client):
        mock_client.return_value.plan.create.return_value = {'id': 'plan_CMD1'}

        out = StringIO()
        call_command('sync_razorpay_plans', stdout=out)

        self.pro.refresh_from_db()
        self.assertEqual(self.pro.razorpay_plan_id, 'plan_CMD1')
        self.assertIn('plan_CMD1', out.getvalue())

    @patch('accounts.razorpay_service._get_client')
    def test_skips_already_synced_plans(self, mock_client):
        self.pro.razorpay_plan_id = 'plan_ALREADY'
        self.pro.save()

        out = StringIO()
        call_command('sync_razorpay_plans', stdout=out)

        self.assertIn('already synced', out.getvalue())
        mock_client.return_value.plan.create.assert_not_called()

    @patch('accounts.razorpay_service._get_client')
    def test_force_resyncs_all(self, mock_client):
        self.pro.razorpay_plan_id = 'plan_OLD'
        self.pro.save()
        mock_client.return_value.plan.create.return_value = {'id': 'plan_FORCED'}

        out = StringIO()
        call_command('sync_razorpay_plans', '--force', stdout=out)

        self.pro.refresh_from_db()
        self.assertEqual(self.pro.razorpay_plan_id, 'plan_FORCED')

    def test_dry_run_no_api_calls(self):
        out = StringIO()
        call_command('sync_razorpay_plans', '--dry-run', stdout=out)

        output = out.getvalue()
        self.assertIn('would sync', output)
        self.assertIn('Dry run', output)
        self.pro.refresh_from_db()
        self.assertEqual(self.pro.razorpay_plan_id, '')
