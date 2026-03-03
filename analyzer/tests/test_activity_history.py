"""
Tests for GET /api/v1/dashboard/activity/history/ — daily activity history.

Covers:
  - Returns daily breakdown with action counts
  - Respects ?days query param
  - Empty history returns empty list
  - Streak and monthly count included
  - Only returns authenticated user's data
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import Plan
from analyzer.models import UserActivity


def _setup_user(username='testuser'):
    Plan.objects.get_or_create(
        slug='free',
        defaults={'name': 'Free', 'billing_cycle': 'free', 'price': 0, 'credits_per_month': 10},
    )
    user = User.objects.create_user(username, f'{username}@example.com', 'pass1234')
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


class ActivityHistoryEndpointTest(TestCase):
    """Tests for GET /api/v1/dashboard/activity/history/."""

    def setUp(self):
        self.user, self.client = _setup_user()

    def test_empty_history(self):
        """Returns empty days list when user has no activity."""
        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['days'], [])
        self.assertEqual(resp.data['total_days_active'], 0)
        self.assertEqual(resp.data['streak_days'], 0)
        self.assertEqual(resp.data['actions_this_month'], 0)

    def test_single_day_activity(self):
        """Records a single day of activity correctly."""
        UserActivity.record(self.user, UserActivity.ACTION_LOGIN)
        UserActivity.record(self.user, UserActivity.ACTION_ANALYSIS)

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_days_active'], 1)
        self.assertEqual(len(resp.data['days']), 1)

        day = resp.data['days'][0]
        self.assertEqual(day['date'], str(timezone.now().date()))
        self.assertEqual(day['action_count'], 2)
        self.assertIn('login', day['actions'])
        self.assertIn('analysis', day['actions'])

    def test_multiple_days(self):
        """History includes multiple days, ordered newest first."""
        today = timezone.now().date()

        # Create activity for today
        UserActivity.record(self.user, UserActivity.ACTION_LOGIN)

        # Create activity for 2 days ago manually
        UserActivity.objects.create(
            user=self.user,
            date=today - timedelta(days=2),
            action_count=3,
            actions={'analysis': 2, 'resume_gen': 1},
        )

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_days_active'], 2)
        # Newest first
        self.assertEqual(resp.data['days'][0]['date'], str(today))
        self.assertEqual(resp.data['days'][1]['date'], str(today - timedelta(days=2)))

    def test_days_param_filters(self):
        """?days=7 only returns last 7 days of history."""
        today = timezone.now().date()

        # Activity today
        UserActivity.record(self.user, UserActivity.ACTION_LOGIN)

        # Activity 30 days ago (outside 7-day window)
        UserActivity.objects.create(
            user=self.user,
            date=today - timedelta(days=30),
            action_count=1,
            actions={'login': 1},
        )

        resp = self.client.get('/api/v1/dashboard/activity/history/?days=7')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_days_active'], 1)

    def test_days_param_default_90(self):
        """Default is 90 days of history."""
        today = timezone.now().date()

        # Activity 80 days ago (within 90-day default)
        UserActivity.objects.create(
            user=self.user,
            date=today - timedelta(days=80),
            action_count=1,
            actions={'login': 1},
        )

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_days_active'], 1)

    def test_days_param_max_365(self):
        """?days cannot exceed 365."""
        resp = self.client.get('/api/v1/dashboard/activity/history/?days=999')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Should not error — clamped to 365

    def test_streak_included(self):
        """Streak days are included in the response."""
        today = timezone.now().date()

        # Create 3-day streak
        for i in range(3):
            UserActivity.objects.create(
                user=self.user,
                date=today - timedelta(days=i),
                action_count=1,
                actions={'login': 1},
            )

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['streak_days'], 3)

    def test_unauthenticated(self):
        """Returns 401 for unauthenticated requests."""
        client = APIClient()
        resp = client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_other_user_data_not_leaked(self):
        """User only sees their own activity."""
        other_user, _ = _setup_user('otheruser')
        UserActivity.record(other_user, UserActivity.ACTION_ANALYSIS)
        UserActivity.record(other_user, UserActivity.ACTION_ANALYSIS)
        UserActivity.record(other_user, UserActivity.ACTION_ANALYSIS)

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['total_days_active'], 0)
        self.assertEqual(resp.data['days'], [])

    def test_action_types_breakdown(self):
        """All action types are correctly tracked in the actions dict."""
        UserActivity.record(self.user, UserActivity.ACTION_LOGIN)
        UserActivity.record(self.user, UserActivity.ACTION_ANALYSIS)
        UserActivity.record(self.user, UserActivity.ACTION_RESUME_GEN)
        UserActivity.record(self.user, UserActivity.ACTION_INTERVIEW_PREP)

        resp = self.client.get('/api/v1/dashboard/activity/history/')
        day = resp.data['days'][0]
        self.assertEqual(day['action_count'], 4)
        self.assertEqual(day['actions']['login'], 1)
        self.assertEqual(day['actions']['analysis'], 1)
        self.assertEqual(day['actions']['resume_gen'], 1)
        self.assertEqual(day['actions']['interview_prep'], 1)
