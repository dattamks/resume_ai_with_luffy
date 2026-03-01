"""
Tests for Phase 15: Conversational Resume Builder.

Covers:
  - ResumeChat / ResumeChatMessage model basics
  - start_session() — scratch, profile, previous
  - process_step() — step handlers (contact, target_role, etc.)
  - advance_step / go_back navigation
  - finalize_resume() — creates GeneratedResume
  - API endpoints — start, list, detail, submit, finalize, delete
  - Credit deduction & refund on failure
  - Active session limit (5)
"""
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status as http_status

from accounts.models import Plan, Wallet, CreditCost
from analyzer.models import (
    ResumeChat, ResumeChatMessage, GeneratedResume,
    Resume, ResumeTemplate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_free_plan():
    plan, _ = Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Free', 'billing_cycle': 'free', 'price': 0,
            'credits_per_month': 10,
        },
    )
    return plan


def _ensure_ats_template():
    tpl, _ = ResumeTemplate.objects.get_or_create(
        slug='ats_classic',
        defaults={
            'name': 'ATS Classic',
            'is_premium': False,
            'is_active': True,
            'sort_order': 0,
        },
    )
    return tpl


def _give_credits(user, amount=100):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = amount
    wallet.save(update_fields=['balance'])


def _seed_builder_cost(cost=2):
    CreditCost.objects.update_or_create(
        action='resume_builder',
        defaults={'cost': cost, 'description': 'Resume builder cost'},
    )


def _create_user(username='chatuser', password='testpass123'):
    user = User.objects.create_user(username=username, password=password)
    return user


def _create_authed_client(user=None):
    if user is None:
        user = _create_user()
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


SAMPLE_RESUME_DATA = {
    'contact': {
        'name': 'Test User',
        'email': 'test@example.com',
        'phone': '555-1234',
        'location': 'New York, NY',
        'linkedin': '',
        'portfolio': '',
    },
    'summary': 'Experienced software engineer.',
    'experience': [
        {
            'title': 'Software Engineer',
            'company': 'Acme Corp',
            'location': 'Remote',
            'start_date': '2020-01',
            'end_date': 'Present',
            'bullets': ['Built microservices', 'Led team of 5'],
        },
    ],
    'education': [
        {
            'degree': 'BS Computer Science',
            'institution': 'MIT',
            'location': 'Cambridge, MA',
            'year': '2020',
            'gpa': '3.8',
        },
    ],
    'skills': {
        'technical': ['Python', 'Django'],
        'tools': ['Git', 'Docker'],
        'soft': ['Leadership'],
    },
    'certifications': [],
    'projects': [],
}


# ── Model Tests ──────────────────────────────────────────────────────────────


class ResumeChatModelTest(TestCase):
    def setUp(self):
        self.user = _create_user()

    def test_create_session(self):
        chat = ResumeChat.objects.create(
            user=self.user,
            source=ResumeChat.SOURCE_SCRATCH,
        )
        self.assertEqual(chat.current_step, ResumeChat.STEP_START)
        self.assertEqual(chat.status, ResumeChat.STATUS_ACTIVE)
        self.assertEqual(chat.resume_data, {})

    def test_advance_step(self):
        chat = ResumeChat.objects.create(user=self.user)
        # start -> contact
        chat.advance_step()
        self.assertEqual(chat.current_step, ResumeChat.STEP_CONTACT)
        # contact -> target_role
        chat.advance_step()
        self.assertEqual(chat.current_step, ResumeChat.STEP_TARGET_ROLE)

    def test_go_back(self):
        chat = ResumeChat.objects.create(user=self.user)
        chat.current_step = ResumeChat.STEP_EDUCATION
        chat.go_back()
        self.assertEqual(chat.current_step, ResumeChat.STEP_EXPERIENCE_REVIEW)

    def test_go_back_at_start_stays(self):
        chat = ResumeChat.objects.create(user=self.user)
        chat.go_back()
        self.assertEqual(chat.current_step, ResumeChat.STEP_START)

    def test_step_number(self):
        chat = ResumeChat.objects.create(user=self.user)
        self.assertEqual(chat.step_number, 1)
        chat.current_step = ResumeChat.STEP_SKILLS
        self.assertEqual(chat.step_number, 7)

    def test_total_steps(self):
        chat = ResumeChat.objects.create(user=self.user)
        self.assertEqual(chat.total_steps, 11)

    def test_str_representation(self):
        chat = ResumeChat.objects.create(
            user=self.user,
            resume_data={'contact': {'name': 'John Doe'}},
        )
        self.assertIn('John Doe', str(chat))

    def test_message_creation(self):
        chat = ResumeChat.objects.create(user=self.user)
        msg = ResumeChatMessage.objects.create(
            chat=chat,
            role=ResumeChatMessage.ROLE_ASSISTANT,
            content='Hello!',
            step=ResumeChat.STEP_START,
            ui_spec={'type': 'buttons', 'options': []},
        )
        self.assertEqual(msg.chat, chat)
        self.assertEqual(msg.role, 'assistant')
        self.assertEqual(chat.messages.count(), 1)


# ── Service Tests ────────────────────────────────────────────────────────────


class StartSessionServiceTest(TestCase):
    def setUp(self):
        self.user = _create_user()

    def test_start_scratch_session(self):
        from analyzer.services.resume_chat_service import start_session
        chat = start_session(self.user, 'scratch')
        self.assertIsInstance(chat, ResumeChat)
        self.assertEqual(chat.source, ResumeChat.SOURCE_SCRATCH)
        # start_session advances to STEP_CONTACT automatically
        self.assertEqual(chat.current_step, ResumeChat.STEP_CONTACT)
        # Should have an initial assistant message
        self.assertTrue(chat.messages.count() > 0)
        first_msg = chat.messages.order_by('created_at').first()
        self.assertEqual(first_msg.role, ResumeChatMessage.ROLE_ASSISTANT)

    def test_start_profile_session_prefills(self):
        """Profile data pre-fills contact info from User model."""
        from analyzer.services.resume_chat_service import start_session
        self.user.first_name = 'Jane'
        self.user.last_name = 'Smith'
        self.user.email = 'jane@example.com'
        self.user.save()
        chat = start_session(self.user, 'profile')
        self.assertEqual(chat.source, ResumeChat.SOURCE_PROFILE)
        contact = chat.resume_data.get('contact', {})
        self.assertEqual(contact.get('email'), 'jane@example.com')

    def test_start_previous_session(self):
        """Session from previous resume -- base_resume_id can be set."""
        from analyzer.services.resume_chat_service import start_session
        resume = Resume.objects.create(
            user=self.user,
            original_filename='test.pdf',
        )
        chat = start_session(self.user, 'previous', base_resume_id=str(resume.id))
        self.assertEqual(chat.source, ResumeChat.SOURCE_PREVIOUS)


class ProcessStepServiceTest(TestCase):
    def setUp(self):
        self.user = _create_user()

    def test_contact_step_update_and_continue(self):
        from analyzer.services.resume_chat_service import start_session, process_step
        chat = start_session(self.user, 'scratch')
        # chat is now at STEP_CONTACT
        self.assertEqual(chat.current_step, ResumeChat.STEP_CONTACT)

        # Update contact fields via update_card action
        contact_data = {
            'name': 'Test User',
            'email': 'test@example.com',
            'phone': '555-0000',
            'location': 'San Francisco, CA',
        }
        messages = process_step(chat, 'update_card', contact_data)
        chat.refresh_from_db()
        self.assertEqual(chat.resume_data['contact']['name'], 'Test User')
        self.assertTrue(len(messages) > 0)

        # Confirm and advance via continue action
        messages = process_step(chat, 'continue', {})
        chat.refresh_from_db()
        self.assertEqual(chat.current_step, ResumeChat.STEP_TARGET_ROLE)

    def test_back_action(self):
        from analyzer.services.resume_chat_service import start_session, process_step
        chat = start_session(self.user, 'scratch')
        # Move forward to education step manually
        chat.current_step = ResumeChat.STEP_EDUCATION
        chat.save()

        messages = process_step(chat, 'back', {})
        chat.refresh_from_db()
        self.assertEqual(chat.current_step, ResumeChat.STEP_EXPERIENCE_REVIEW)


class FinalizeResumeServiceTest(TestCase):
    def setUp(self):
        self.user = _create_user()
        _ensure_ats_template()

    def test_finalize_creates_generated_resume(self):
        from analyzer.services.resume_chat_service import finalize_resume
        chat = ResumeChat.objects.create(
            user=self.user,
            source=ResumeChat.SOURCE_SCRATCH,
            current_step=ResumeChat.STEP_REVIEW,
            status=ResumeChat.STATUS_ACTIVE,
            resume_data=SAMPLE_RESUME_DATA,
        )
        gen = finalize_resume(chat, 'ats_classic', 'pdf')
        self.assertIsNotNone(gen)
        self.assertEqual(gen.user, self.user)
        self.assertEqual(gen.template, 'ats_classic')
        self.assertEqual(gen.format, 'pdf')
        self.assertEqual(gen.resume_content, SAMPLE_RESUME_DATA)
        self.assertEqual(gen.status, GeneratedResume.STATUS_PENDING)
        chat.refresh_from_db()
        self.assertEqual(chat.status, ResumeChat.STATUS_COMPLETED)
        self.assertEqual(chat.generated_resume, gen)

    def test_finalize_rejects_empty_resume_data(self):
        from analyzer.services.resume_chat_service import finalize_resume
        chat = ResumeChat.objects.create(
            user=self.user,
            source=ResumeChat.SOURCE_SCRATCH,
            current_step=ResumeChat.STEP_REVIEW,
            resume_data={},
        )
        with self.assertRaises(ValueError):
            finalize_resume(chat, 'ats_classic', 'pdf')


# ── API Endpoint Tests ───────────────────────────────────────────────────────


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatStartViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()
        _ensure_free_plan()

    def test_start_scratch(self):
        resp = self.client.post('/api/v1/resume-chat/start/', {'source': 'scratch'})
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)
        data = resp.json()
        self.assertIn('id', data)
        self.assertEqual(data['source'], 'scratch')
        # start_session advances to contact step
        self.assertEqual(data['current_step'], 'contact')

    def test_start_profile(self):
        resp = self.client.post('/api/v1/resume-chat/start/', {'source': 'profile'})
        self.assertEqual(resp.status_code, http_status.HTTP_201_CREATED)

    def test_start_requires_auth(self):
        client = APIClient()
        resp = client.post('/api/v1/resume-chat/start/', {'source': 'scratch'})
        self.assertEqual(resp.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_start_invalid_source(self):
        resp = self.client.post('/api/v1/resume-chat/start/', {'source': 'invalid'})
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)

    def test_active_session_limit(self):
        """Users are limited to 5 active sessions -- returns 400."""
        for _ in range(5):
            ResumeChat.objects.create(
                user=self.user,
                source=ResumeChat.SOURCE_SCRATCH,
                status=ResumeChat.STATUS_ACTIVE,
            )
        resp = self.client.post('/api/v1/resume-chat/start/', {'source': 'scratch'})
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)
        self.assertIn('Maximum 5', resp.json()['detail'])


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatListViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()

    def test_list_empty(self):
        resp = self.client.get('/api/v1/resume-chat/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        # List view returns a flat array
        self.assertEqual(resp.json(), [])

    def test_list_returns_own_sessions(self):
        ResumeChat.objects.create(user=self.user)
        other_user = _create_user('other')
        ResumeChat.objects.create(user=other_user)
        resp = self.client.get('/api/v1/resume-chat/')
        self.assertEqual(len(resp.json()), 1)

    def test_filter_by_status(self):
        ResumeChat.objects.create(
            user=self.user, status=ResumeChat.STATUS_ACTIVE,
        )
        ResumeChat.objects.create(
            user=self.user, status=ResumeChat.STATUS_COMPLETED,
        )
        resp = self.client.get('/api/v1/resume-chat/?status=active')
        self.assertEqual(len(resp.json()), 1)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatDetailViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()
        self.chat = ResumeChat.objects.create(user=self.user)

    def test_get_detail(self):
        resp = self.client.get(f'/api/v1/resume-chat/{self.chat.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIn('messages', resp.json())

    def test_get_detail_wrong_user(self):
        other_user = _create_user('other2')
        other_client, _ = _create_authed_client(other_user)
        resp = other_client.get(f'/api/v1/resume-chat/{self.chat.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_delete_session(self):
        resp = self.client.delete(f'/api/v1/resume-chat/{self.chat.id}/')
        self.assertEqual(resp.status_code, http_status.HTTP_204_NO_CONTENT)
        self.assertFalse(ResumeChat.objects.filter(id=self.chat.id).exists())


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatSubmitViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()
        _ensure_free_plan()

    def test_submit_contact_update(self):
        chat = ResumeChat.objects.create(
            user=self.user,
            current_step=ResumeChat.STEP_CONTACT,
            status=ResumeChat.STATUS_ACTIVE,
            resume_data={
                'contact': {'name': '', 'email': '', 'phone': '', 'location': '', 'linkedin': '', 'portfolio': ''},
                'summary': '', 'experience': [], 'education': [],
                'skills': {'technical': [], 'tools': [], 'soft': []},
                'certifications': [], 'projects': [],
            },
        )
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/submit/',
            {
                'action': 'update_card',
                'payload': {
                    'name': 'Alice',
                    'email': 'alice@example.com',
                    'phone': '555-1111',
                    'location': 'Boston',
                },
            },
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        chat.refresh_from_db()
        self.assertEqual(chat.resume_data['contact']['name'], 'Alice')
        data = resp.json()
        self.assertIn('messages', data)
        self.assertIn('current_step', data)

    def test_submit_wrong_user(self):
        other_user = _create_user('other3')
        chat = ResumeChat.objects.create(
            user=other_user,
            status=ResumeChat.STATUS_ACTIVE,
        )
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/submit/',
            {'action': 'submit', 'payload': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)

    def test_submit_completed_session(self):
        """Completed sessions return 404 (query filters by status=active)."""
        chat = ResumeChat.objects.create(
            user=self.user,
            status=ResumeChat.STATUS_COMPLETED,
        )
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/submit/',
            {'action': 'submit', 'payload': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_404_NOT_FOUND)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatFinalizeViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()
        _ensure_free_plan()
        _ensure_ats_template()
        _seed_builder_cost()
        _give_credits(self.user, 100)

    def _make_ready_chat(self):
        return ResumeChat.objects.create(
            user=self.user,
            source=ResumeChat.SOURCE_SCRATCH,
            current_step=ResumeChat.STEP_REVIEW,
            status=ResumeChat.STATUS_ACTIVE,
            resume_data=SAMPLE_RESUME_DATA,
        )

    @patch('analyzer.tasks.render_builder_resume_task.delay')
    def test_finalize_success(self, mock_delay):
        chat = self._make_ready_chat()
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/finalize/',
            {'template': 'ats_classic', 'format': 'pdf'},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_202_ACCEPTED)
        data = resp.json()
        self.assertIn('id', data)
        self.assertEqual(data['status'], 'pending')
        self.assertEqual(data['credits_used'], 2)
        mock_delay.assert_called_once()

    def test_finalize_insufficient_credits(self):
        _give_credits(self.user, 0)
        chat = self._make_ready_chat()
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/finalize/',
            {'template': 'ats_classic', 'format': 'pdf'},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_402_PAYMENT_REQUIRED)

    def test_finalize_invalid_template(self):
        chat = self._make_ready_chat()
        resp = self.client.post(
            f'/api/v1/resume-chat/{chat.id}/finalize/',
            {'template': 'nonexistent', 'format': 'pdf'},
            format='json',
        )
        self.assertEqual(resp.status_code, http_status.HTTP_400_BAD_REQUEST)


@override_settings(
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
class ResumeChatResumesViewTest(TestCase):
    def setUp(self):
        self.client, self.user = _create_authed_client()

    def test_list_resumes(self):
        resp = self.client.get('/api/v1/resume-chat/resumes/')
        self.assertEqual(resp.status_code, http_status.HTTP_200_OK)
        self.assertIn('resumes', resp.json())


# ── Celery Task Tests ────────────────────────────────────────────────────────


class RenderBuilderResumeTaskTest(TestCase):
    def setUp(self):
        self.user = _create_user()
        _ensure_ats_template()

    @patch('analyzer.services.template_registry.get_renderer')
    def test_render_success(self, mock_get_renderer):
        mock_renderer = MagicMock(return_value=b'%PDF fake')
        mock_get_renderer.return_value = mock_renderer

        gen = GeneratedResume.objects.create(
            user=self.user,
            resume_content=SAMPLE_RESUME_DATA,
            template='ats_classic',
            format='pdf',
            status=GeneratedResume.STATUS_PENDING,
        )

        from analyzer.tasks import render_builder_resume_task
        render_builder_resume_task(str(gen.id))

        gen.refresh_from_db()
        self.assertEqual(gen.status, GeneratedResume.STATUS_DONE)
        self.assertTrue(gen.file)
        mock_renderer.assert_called_once_with(SAMPLE_RESUME_DATA)

    @patch('analyzer.services.template_registry.get_renderer')
    def test_render_failure_sets_failed(self, mock_get_renderer):
        mock_get_renderer.side_effect = Exception('Render failed')

        gen = GeneratedResume.objects.create(
            user=self.user,
            resume_content=SAMPLE_RESUME_DATA,
            template='ats_classic',
            format='pdf',
            status=GeneratedResume.STATUS_PENDING,
        )

        from analyzer.tasks import render_builder_resume_task
        render_builder_resume_task(str(gen.id))

        gen.refresh_from_db()
        self.assertEqual(gen.status, GeneratedResume.STATUS_FAILED)
        self.assertIn('Render failed', gen.error_message)

    def test_render_nonexistent_id(self):
        """Task silently returns if GeneratedResume doesn't exist."""
        from analyzer.tasks import render_builder_resume_task
        render_builder_resume_task(str(uuid.uuid4()))  # Should not raise
