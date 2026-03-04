"""
Tests for the Admin Daily Digest feature:
  - compute_digest_metrics() aggregation service
  - send_admin_digest_task() Celery task
  - ADMIN_DIGEST_EMAILS setting
  - EmailTemplate seeding
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone


def _ensure_free_plan():
    from accounts.models import Plan
    Plan.objects.get_or_create(
        slug='free',
        defaults={'name': 'Free', 'billing_cycle': 'free', 'price': 0, 'credits_per_month': 2},
    )


def _seed_admin_digest_template():
    """Create the admin-daily-digest email template for testing."""
    from accounts.models import EmailTemplate
    EmailTemplate.objects.get_or_create(
        slug='admin-daily-digest',
        defaults={
            'name': 'Admin Daily Digest',
            'category': 'admin',
            'subject': '{{ app_name }} Admin Digest — {{ report_time_ist }}',
            'html_body': '<p>Report: {{ report_time_ist }}</p>',
            'plain_text_body': 'Report: {{ report_time_ist }}',
            'is_active': True,
        },
    )


# ── Metrics Aggregation Tests ────────────────────────────────────────────────


class DigestMetricsTests(TestCase):
    """Test compute_digest_metrics() returns correct structure and data."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_free_plan()

    def setUp(self):
        from accounts.models import Plan, UserProfile, Wallet
        self.user = User.objects.create_user(
            username='digestuser', password='pass1234', email='d@test.com',
        )
        plan = Plan.objects.get(slug='free')
        UserProfile.objects.update_or_create(
            user=self.user, defaults={'plan': plan},
        )
        Wallet.objects.get_or_create(user=self.user, defaults={'balance': 10})

    def test_returns_all_sections(self):
        """compute_digest_metrics() returns all 11 metric sections + metadata."""
        from analyzer.services.admin_digest import compute_digest_metrics

        metrics = compute_digest_metrics()

        expected_sections = [
            'report_time_ist', 'period',
            'users', 'revenue', 'credits', 'analyses', 'resumes',
            'llm', 'job_alerts', 'features', 'news', 'notifications', 'infra',
        ]
        for key in expected_sections:
            self.assertIn(key, metrics, f'Missing section: {key}')

    def test_users_section_structure(self):
        """Users section has new_signups, total_users, dau, plan_distribution, auth_providers."""
        from analyzer.services.admin_digest import compute_digest_metrics

        metrics = compute_digest_metrics()
        users = metrics['users']

        self.assertIn('new_signups', users)
        self.assertIn('total_users', users)
        self.assertIn('dau', users)
        self.assertIn('plan_distribution', users)
        self.assertIn('auth_providers', users)
        self.assertGreaterEqual(users['total_users'], 1)

    def test_new_signup_counted(self):
        """A user created within 24h should appear in new_signups."""
        from analyzer.services.admin_digest import compute_digest_metrics

        metrics = compute_digest_metrics()
        # setUp user was created just now — should be counted
        self.assertGreaterEqual(metrics['users']['new_signups'], 1)

    def test_revenue_section_structure(self):
        """Revenue section has expected keys."""
        from analyzer.services.admin_digest import compute_digest_metrics

        revenue = compute_digest_metrics()['revenue']
        for key in ['captured_count', 'captured_total_inr', 'failed_payments',
                     'new_subscriptions', 'subscription_status', 'webhooks_received']:
            self.assertIn(key, revenue)

    def test_credits_section_structure(self):
        """Credits section has expected keys."""
        from analyzer.services.admin_digest import compute_digest_metrics

        credits = compute_digest_metrics()['credits']
        for key in ['plan_credits_granted', 'topup_credits', 'credits_consumed',
                     'credits_refunded', 'zero_balance_users']:
            self.assertIn(key, credits)

    def test_analyses_section_structure(self):
        """Analyses section has total, done, failed, avg scores."""
        from analyzer.services.admin_digest import compute_digest_metrics

        analyses = compute_digest_metrics()['analyses']
        for key in ['total', 'done', 'failed', 'avg_ats_score', 'avg_overall_grade']:
            self.assertIn(key, analyses)

    def test_analyses_counted(self):
        """Analyses created in last 24h are counted."""
        from analyzer.models import ResumeAnalysis, Resume
        from analyzer.services.admin_digest import compute_digest_metrics

        resume = Resume.objects.create(user=self.user, file='test.pdf')
        ResumeAnalysis.objects.create(
            user=self.user, resume=resume, status='done',
            ats_score=85, overall_grade=4.0, jd_role='SDE',
        )

        analyses = compute_digest_metrics()['analyses']
        self.assertGreaterEqual(analyses['total'], 1)
        self.assertGreaterEqual(analyses['done'], 1)

    def test_resumes_section_structure(self):
        """Resumes section has upload/generation/builder counts."""
        from analyzer.services.admin_digest import compute_digest_metrics

        resumes = compute_digest_metrics()['resumes']
        for key in ['uploaded', 'generated', 'builder_sessions']:
            self.assertIn(key, resumes)

    def test_llm_section_structure(self):
        """LLM section has calls, tokens, cost, failure rate."""
        from analyzer.services.admin_digest import compute_digest_metrics

        llm = compute_digest_metrics()['llm']
        for key in ['total_calls', 'total_tokens', 'estimated_cost_usd',
                     'failure_rate_pct', 'avg_duration_sec']:
            self.assertIn(key, llm)

    def test_llm_usage_counted(self):
        """LLM responses created in last 24h are counted."""
        from analyzer.models import LLMResponse
        from analyzer.services.admin_digest import compute_digest_metrics

        LLMResponse.objects.create(
            user=self.user, model_used='gpt-4o', status='done',
            call_purpose='analysis', prompt_tokens=500, completion_tokens=200,
            total_tokens=700, estimated_cost_usd=0.012, duration_seconds=3.5,
        )

        llm = compute_digest_metrics()['llm']
        self.assertGreaterEqual(llm['total_calls'], 1)
        self.assertGreaterEqual(llm['total_tokens'], 700)

    def test_job_alerts_section_structure(self):
        """Job alerts section has runs, matches, relevance."""
        from analyzer.services.admin_digest import compute_digest_metrics

        ja = compute_digest_metrics()['job_alerts']
        for key in ['alert_runs', 'jobs_discovered', 'jobs_matched',
                     'new_discovered_jobs', 'avg_relevance_score', 'active_alerts_total']:
            self.assertIn(key, ja)

    def test_features_section_structure(self):
        """Features section has interview preps, cover letters, actions."""
        from analyzer.services.admin_digest import compute_digest_metrics

        features = compute_digest_metrics()['features']
        for key in ['interview_preps', 'cover_letters', 'total_actions_today']:
            self.assertIn(key, features)

    def test_news_section_structure(self):
        """News section has synced count, flagged, unapproved."""
        from analyzer.services.admin_digest import compute_digest_metrics

        news = compute_digest_metrics()['news']
        for key in ['synced_today', 'by_category', 'flagged', 'unapproved']:
            self.assertIn(key, news)

    def test_news_snippets_counted(self):
        """News snippets created in last 24h are counted."""
        from analyzer.models import NewsSnippet
        from analyzer.services.admin_digest import compute_digest_metrics

        NewsSnippet.objects.create(
            uuid=uuid.uuid4(), headline='Test News', summary='Summary',
            source_url='https://example.com/news/1', source_name='Test',
            category='hiring', relevance_score=8, sentiment='positive',
            published_at=timezone.now(),
        )

        news = compute_digest_metrics()['news']
        self.assertGreaterEqual(news['synced_today'], 1)

    def test_notifications_section_structure(self):
        """Notifications section has created_today, unread, contact."""
        from analyzer.services.admin_digest import compute_digest_metrics

        notifs = compute_digest_metrics()['notifications']
        for key in ['created_today', 'unread_total', 'contact_submissions']:
            self.assertIn(key, notifs)

    def test_infra_section_structure(self):
        """Infra section has crawl source counts."""
        from analyzer.services.admin_digest import compute_digest_metrics

        infra = compute_digest_metrics()['infra']
        for key in ['stale_crawl_sources', 'total_crawl_sources']:
            self.assertIn(key, infra)

    def test_report_time_ist_format(self):
        """Report time should be in IST format string."""
        from analyzer.services.admin_digest import compute_digest_metrics

        metrics = compute_digest_metrics()
        self.assertIn('IST', metrics['report_time_ist'])
        self.assertEqual(metrics['period'], 'Last 24 hours')

    def test_zero_balance_users_counted(self):
        """Users with zero wallet balance are counted."""
        from accounts.models import Wallet
        from analyzer.services.admin_digest import compute_digest_metrics

        # Set our test user's wallet to 0
        Wallet.objects.filter(user=self.user).update(balance=0)

        credits = compute_digest_metrics()['credits']
        self.assertGreaterEqual(credits['zero_balance_users'], 1)


# ── Celery Task Tests ────────────────────────────────────────────────────────


class AdminDigestTaskTests(TestCase):
    """Test send_admin_digest_task() Celery task."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_free_plan()

    @override_settings(ADMIN_DIGEST_EMAILS=[])
    def test_skips_when_no_recipients(self):
        """Task exits early when ADMIN_DIGEST_EMAILS is empty."""
        from analyzer.tasks import send_admin_digest_task

        # Should not raise, should just log warning and return
        send_admin_digest_task()

    @override_settings(ADMIN_DIGEST_EMAILS=['admin@test.com', 'boss@test.com'])
    @patch('accounts.email_utils.send_templated_email')
    def test_sends_to_all_recipients(self, mock_send):
        """Task sends digest to all configured email addresses."""
        from analyzer.tasks import send_admin_digest_task
        _seed_admin_digest_template()

        send_admin_digest_task()

        self.assertEqual(mock_send.call_count, 2)
        recipients = [call.kwargs['recipient'] for call in mock_send.call_args_list]
        self.assertIn('admin@test.com', recipients)
        self.assertIn('boss@test.com', recipients)

    @override_settings(ADMIN_DIGEST_EMAILS=['admin@test.com'])
    @patch('accounts.email_utils.send_templated_email')
    def test_uses_correct_template_slug(self, mock_send):
        """Task uses 'admin-daily-digest' template slug."""
        from analyzer.tasks import send_admin_digest_task
        _seed_admin_digest_template()

        send_admin_digest_task()

        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs['slug'], 'admin-daily-digest')

    @override_settings(ADMIN_DIGEST_EMAILS=['admin@test.com'])
    @patch('accounts.email_utils.send_templated_email')
    def test_context_has_all_metrics(self, mock_send):
        """Task passes all metric keys to the email template."""
        from analyzer.tasks import send_admin_digest_task
        _seed_admin_digest_template()

        send_admin_digest_task()

        ctx = mock_send.call_args.kwargs['context']

        # Spot-check representative keys from each section
        expected_keys = [
            'report_time_ist', 'period',
            'new_signups', 'total_users', 'dau',
            'captured_total_inr', 'failed_payments',
            'credits_consumed', 'zero_balance_users',
            'analyses_total', 'avg_ats_score',
            'resumes_uploaded', 'resumes_generated',
            'llm_total_calls', 'llm_cost_usd',
            'alert_runs', 'active_alerts_total',
            'interview_preps', 'cover_letters',
            'news_synced', 'news_flagged',
            'notifications_created', 'contact_submissions',
            'stale_crawl_sources',
        ]
        for key in expected_keys:
            self.assertIn(key, ctx, f'Missing context key: {key}')

    @override_settings(ADMIN_DIGEST_EMAILS=['admin@test.com'])
    @patch('accounts.email_utils.send_templated_email', side_effect=Exception('SMTP down'))
    def test_handles_send_failure_gracefully(self, mock_send):
        """Task does not crash if email sending fails."""
        from analyzer.tasks import send_admin_digest_task
        _seed_admin_digest_template()

        # Should not raise — catches per-recipient exceptions
        send_admin_digest_task()

    @override_settings(ADMIN_DIGEST_EMAILS=['a@test.com', 'b@test.com', 'c@test.com'])
    @patch('accounts.email_utils.send_templated_email')
    def test_partial_failure_continues(self, mock_send):
        """If one recipient fails, the rest still get sent."""
        from analyzer.tasks import send_admin_digest_task
        _seed_admin_digest_template()

        # First call succeeds, second fails, third succeeds
        mock_send.side_effect = [True, Exception('fail'), True]

        send_admin_digest_task()

        self.assertEqual(mock_send.call_count, 3)


# ── Settings Tests ───────────────────────────────────────────────────────────


class AdminDigestSettingsTests(TestCase):
    """Test ADMIN_DIGEST_EMAILS configuration."""

    @override_settings(ADMIN_DIGEST_EMAILS=['a@x.com', 'b@x.com'])
    def test_setting_is_list(self):
        """ADMIN_DIGEST_EMAILS is a list of email strings."""
        from django.conf import settings
        self.assertIsInstance(settings.ADMIN_DIGEST_EMAILS, list)
        self.assertEqual(len(settings.ADMIN_DIGEST_EMAILS), 2)

    @override_settings(ADMIN_DIGEST_EMAILS=[])
    def test_empty_setting(self):
        """Empty ADMIN_DIGEST_EMAILS is valid (task skips sending)."""
        from django.conf import settings
        self.assertEqual(settings.ADMIN_DIGEST_EMAILS, [])


# ── Celery Beat Schedule Tests ───────────────────────────────────────────────


class AdminDigestScheduleTests(TestCase):
    """Test Celery Beat schedule entries for admin digest."""

    def test_morning_schedule_exists(self):
        """admin-digest-morning is in CELERY_BEAT_SCHEDULE."""
        from django.conf import settings
        self.assertIn('admin-digest-morning', settings.CELERY_BEAT_SCHEDULE)

    def test_night_schedule_exists(self):
        """admin-digest-night is in CELERY_BEAT_SCHEDULE."""
        from django.conf import settings
        self.assertIn('admin-digest-night', settings.CELERY_BEAT_SCHEDULE)

    def test_morning_schedule_task(self):
        """Morning schedule points to the correct task."""
        from django.conf import settings
        entry = settings.CELERY_BEAT_SCHEDULE['admin-digest-morning']
        self.assertEqual(entry['task'], 'analyzer.tasks.send_admin_digest_task')

    def test_night_schedule_task(self):
        """Night schedule points to the correct task."""
        from django.conf import settings
        entry = settings.CELERY_BEAT_SCHEDULE['admin-digest-night']
        self.assertEqual(entry['task'], 'analyzer.tasks.send_admin_digest_task')

    def test_morning_ist_time(self):
        """Morning schedule fires at 3:30 UTC = 9:00 AM IST."""
        from django.conf import settings
        sched = settings.CELERY_BEAT_SCHEDULE['admin-digest-morning']['schedule']
        self.assertEqual(sched.hour, {3})
        self.assertEqual(sched.minute, {30})

    def test_night_ist_time(self):
        """Night schedule fires at 17:30 UTC = 11:00 PM IST."""
        from django.conf import settings
        sched = settings.CELERY_BEAT_SCHEDULE['admin-digest-night']['schedule']
        self.assertEqual(sched.hour, {17})
        self.assertEqual(sched.minute, {30})


# ── Seed Command Tests ───────────────────────────────────────────────────────


class SeedEmailTemplateTests(TestCase):
    """Test that seed_email_templates includes the admin digest template."""

    def test_admin_digest_template_in_seeds(self):
        """The admin-daily-digest slug exists in the TEMPLATES list."""
        from accounts.management.commands.seed_email_templates import TEMPLATES
        slugs = [t['slug'] for t in TEMPLATES]
        self.assertIn('admin-daily-digest', slugs)

    def test_admin_digest_template_has_required_fields(self):
        """The template data has all required fields."""
        from accounts.management.commands.seed_email_templates import TEMPLATES
        tmpl = next(t for t in TEMPLATES if t['slug'] == 'admin-daily-digest')
        for field in ['name', 'category', 'subject', 'html_body', 'plain_text_body']:
            self.assertIn(field, tmpl)
            self.assertTrue(tmpl[field], f'{field} should not be empty')
