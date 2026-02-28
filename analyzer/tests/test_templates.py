"""
Tests for the resume template marketplace:
- ResumeTemplate model
- Template listing API
- Plan gating (premium_templates on Plan)
- Template registry
- Renderer output validation
- GenerateResumeView with template selection
"""
import uuid
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Plan, UserProfile
from analyzer.models import ResumeTemplate, ResumeAnalysis, Resume, GeneratedResume
from analyzer.services.template_registry import (
    get_renderer, get_available_slugs, TEMPLATE_RENDERERS,
)


SAMPLE_RESUME_CONTENT = {
    'contact': {
        'name': 'Jane Doe', 'email': 'jane@example.com',
        'phone': '+1 555-1234', 'location': 'San Francisco, CA',
        'linkedin': 'linkedin.com/in/janedoe', 'portfolio': 'janedoe.dev',
    },
    'summary': 'Experienced software engineer with 8+ years.',
    'experience': [{
        'title': 'Senior Engineer', 'company': 'TechCorp',
        'location': 'SF', 'start_date': 'Jan 2020', 'end_date': 'Present',
        'bullets': ['Led team of 5', 'Reduced latency by 40%'],
    }],
    'education': [{
        'degree': 'BSc Computer Science', 'institution': 'MIT',
        'year': '2016', 'gpa': '3.8', 'location': 'Cambridge, MA',
    }],
    'skills': {
        'technical': ['Python', 'Django'],
        'tools': ['Docker', 'AWS'],
        'soft': ['Leadership'],
    },
    'certifications': [{'name': 'AWS SA', 'issuer': 'Amazon', 'year': '2023'}],
    'projects': [{
        'name': 'CLI Tool', 'description': 'A CLI',
        'technologies': ['Go'], 'url': 'github.com/test',
    }],
}


class ResumeTemplateModelTests(TestCase):
    """Test ResumeTemplate model basics."""

    def test_create_template(self):
        t = ResumeTemplate.objects.create(
            name='Test Template', slug='test_tmpl',
            description='A test.', category='professional',
            is_premium=False, sort_order=99,
        )
        self.assertEqual(t.slug, 'test_tmpl')
        self.assertFalse(t.is_premium)
        self.assertTrue(t.is_active)
        self.assertIn('Test Template', str(t))

    def test_premium_str_tag(self):
        t = ResumeTemplate.objects.create(
            name='Premium', slug='prem', is_premium=True,
        )
        self.assertIn('[PREMIUM]', str(t))

    def test_slug_unique(self):
        ResumeTemplate.objects.create(name='T1', slug='unique_slug')
        with self.assertRaises(Exception):
            ResumeTemplate.objects.create(name='T2', slug='unique_slug')

    def test_ordering(self):
        ResumeTemplate.objects.create(name='B', slug='b', sort_order=2)
        ResumeTemplate.objects.create(name='A', slug='a', sort_order=1)
        templates = list(ResumeTemplate.objects.values_list('slug', flat=True))
        self.assertEqual(templates[0], 'a')


class TemplateRegistryTests(TestCase):
    """Test the template_registry module."""

    def test_all_slugs_present(self):
        slugs = get_available_slugs()
        expected = ['ats_classic', 'creative', 'executive', 'minimal', 'modern']
        self.assertEqual(slugs, expected)

    def test_get_renderer_pdf(self):
        renderer = get_renderer('ats_classic', 'pdf')
        self.assertTrue(callable(renderer))
        self.assertEqual(renderer.__name__, 'render_resume_pdf')

    def test_get_renderer_docx(self):
        renderer = get_renderer('modern', 'docx')
        self.assertTrue(callable(renderer))
        self.assertEqual(renderer.__name__, 'render_modern_docx')

    def test_unknown_slug_raises(self):
        with self.assertRaises(ValueError) as ctx:
            get_renderer('nonexistent', 'pdf')
        self.assertIn('nonexistent', str(ctx.exception))

    def test_unknown_format_raises(self):
        with self.assertRaises(ValueError) as ctx:
            get_renderer('ats_classic', 'html')
        self.assertIn('html', str(ctx.exception))


class RendererOutputTests(TestCase):
    """Test that every registered renderer produces valid output."""

    def test_all_renderers_produce_bytes(self):
        for slug in get_available_slugs():
            for fmt in ('pdf', 'docx'):
                renderer = get_renderer(slug, fmt)
                result = renderer(SAMPLE_RESUME_CONTENT)
                self.assertIsInstance(result, bytes, f'{slug}/{fmt} did not return bytes')
                self.assertGreater(len(result), 100, f'{slug}/{fmt} output too small')

    def test_renderers_handle_empty_content(self):
        for slug in get_available_slugs():
            for fmt in ('pdf', 'docx'):
                renderer = get_renderer(slug, fmt)
                result = renderer({})
                self.assertIsInstance(result, bytes, f'{slug}/{fmt} crashed on empty input')

    def test_renderers_handle_minimal_content(self):
        minimal = {'contact': {'name': 'Test'}}
        for slug in get_available_slugs():
            for fmt in ('pdf', 'docx'):
                renderer = get_renderer(slug, fmt)
                result = renderer(minimal)
                self.assertIsInstance(result, bytes)

    def test_renderers_handle_special_characters(self):
        content = {
            'contact': {'name': 'José García <>&"\'', 'email': 'jose@例え.jp'},
            'summary': 'Expert in C++ & data<analysis>.',
            'experience': [{'title': 'Développeur', 'company': 'Ñ Corp', 'bullets': ['Résumé & CV']}],
            'skills': {'technical': ['C#', 'F#'], 'tools': [], 'soft': []},
        }
        for slug in get_available_slugs():
            for fmt in ('pdf', 'docx'):
                renderer = get_renderer(slug, fmt)
                result = renderer(content)
                self.assertIsInstance(result, bytes)


class TemplateListAPITests(TestCase):
    """Test GET /api/v1/templates/ endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.free_plan = Plan.objects.create(
            name='Free Test', slug='free_test', price=0,
            billing_cycle='free', premium_templates=False,
        )
        self.pro_plan = Plan.objects.create(
            name='Pro Test', slug='pro_test', price=999,
            billing_cycle='monthly', premium_templates=True,
        )
        # Create templates
        self.tmpl_free = ResumeTemplate.objects.create(
            name='Free Template', slug='free_tmpl',
            is_premium=False, is_active=True, sort_order=0,
        )
        self.tmpl_premium = ResumeTemplate.objects.create(
            name='Premium Template', slug='premium_tmpl',
            is_premium=True, is_active=True, sort_order=1,
        )
        self.tmpl_inactive = ResumeTemplate.objects.create(
            name='Inactive', slug='inactive_tmpl',
            is_premium=False, is_active=False, sort_order=99,
        )

    def _create_user(self, username, plan):
        user = User.objects.create_user(username=username, password='testpass123')
        profile = UserProfile.objects.get(user=user)
        profile.plan = plan
        profile.save()
        # Refresh to clear cached reverse OneToOne accessor
        user.refresh_from_db()
        return user

    def test_requires_auth(self):
        resp = self.client.get('/api/v1/templates/')
        self.assertEqual(resp.status_code, 401)

    def test_lists_active_only(self):
        user = self._create_user('freeuser', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/v1/templates/')
        self.assertEqual(resp.status_code, 200)
        slugs = [t['slug'] for t in resp.data['results']]
        self.assertIn('free_tmpl', slugs)
        self.assertIn('premium_tmpl', slugs)
        self.assertNotIn('inactive_tmpl', slugs)

    def test_accessible_flag_free_user(self):
        user = self._create_user('freeuser2', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/v1/templates/')
        templates = {t['slug']: t for t in resp.data['results']}
        self.assertTrue(templates['free_tmpl']['accessible'])
        self.assertFalse(templates['premium_tmpl']['accessible'])

    def test_accessible_flag_pro_user(self):
        user = self._create_user('prouser', self.pro_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.get('/api/v1/templates/')
        templates = {t['slug']: t for t in resp.data['results']}
        self.assertTrue(templates['free_tmpl']['accessible'])
        self.assertTrue(templates['premium_tmpl']['accessible'])


class PremiumTemplateGatingTests(TestCase):
    """Test plan gating when generating resumes with premium templates."""

    def setUp(self):
        self.client = APIClient()
        self.free_plan = Plan.objects.create(
            name='FreeGate', slug='freegate', price=0,
            billing_cycle='free', premium_templates=False,
        )
        self.pro_plan = Plan.objects.create(
            name='ProGate', slug='progate', price=999,
            billing_cycle='monthly', premium_templates=True,
        )
        # Create templates in DB
        ResumeTemplate.objects.create(
            name='ATS Classic', slug='ats_classic',
            is_premium=False, is_active=True,
        )
        ResumeTemplate.objects.create(
            name='Modern', slug='modern',
            is_premium=True, is_active=True,
        )

    def _create_user_with_analysis(self, username, plan):
        user = User.objects.create_user(username=username, password='testpass123')
        profile = UserProfile.objects.get(user=user)
        profile.plan = plan
        profile.save()
        # Refresh to clear cached reverse OneToOne accessor
        user.refresh_from_db()
        resume = Resume.objects.create(
            user=user, file='resumes/test.pdf',
            original_filename='test.pdf', file_hash=uuid.uuid4().hex,
        )
        analysis = ResumeAnalysis.objects.create(
            user=user, resume=resume,
            status=ResumeAnalysis.STATUS_DONE,
            jd_text='Test JD', jd_input_type='text',
        )
        return user, analysis

    @patch('analyzer.views.deduct_credits')
    @patch('analyzer.views.generate_improved_resume_task')
    def test_free_user_can_use_free_template(self, mock_task, mock_credits):
        mock_credits.return_value = {'cost': 1, 'balance_after': 9}
        mock_task.delay.return_value = None
        user, analysis = self._create_user_with_analysis('free1', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/v1/analyses/{analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, 202)

    def test_free_user_blocked_from_premium_template(self):
        user, analysis = self._create_user_with_analysis('free2', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/v1/analyses/{analysis.pk}/generate-resume/',
            {'template': 'modern', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Premium template', resp.data['detail'])

    @patch('analyzer.views.deduct_credits')
    @patch('analyzer.views.generate_improved_resume_task')
    def test_pro_user_can_use_premium_template(self, mock_task, mock_credits):
        mock_credits.return_value = {'cost': 1, 'balance_after': 9}
        mock_task.delay.return_value = None
        user, analysis = self._create_user_with_analysis('pro1', self.pro_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/v1/analyses/{analysis.pk}/generate-resume/',
            {'template': 'modern', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, 202)

    def test_inactive_template_rejected(self):
        ResumeTemplate.objects.create(
            name='Hidden', slug='hidden_tmpl',
            is_premium=False, is_active=False,
        )
        user, analysis = self._create_user_with_analysis('free3', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/v1/analyses/{analysis.pk}/generate-resume/',
            {'template': 'hidden_tmpl', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not available', str(resp.data))

    def test_nonexistent_template_rejected(self):
        user, analysis = self._create_user_with_analysis('free4', self.free_plan)
        self.client.force_authenticate(user=user)
        resp = self.client.post(
            f'/api/v1/analyses/{analysis.pk}/generate-resume/',
            {'template': 'does_not_exist', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, 400)


class SeedTemplatesCommandTests(TestCase):
    """Test the seed_templates management command."""

    def test_seed_creates_templates(self):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command('seed_templates', stdout=out)
        self.assertEqual(ResumeTemplate.objects.count(), 5)
        self.assertTrue(ResumeTemplate.objects.filter(slug='ats_classic').exists())
        self.assertTrue(ResumeTemplate.objects.filter(slug='modern').exists())
        self.assertTrue(ResumeTemplate.objects.filter(slug='executive').exists())
        self.assertTrue(ResumeTemplate.objects.filter(slug='creative').exists())
        self.assertTrue(ResumeTemplate.objects.filter(slug='minimal').exists())

    def test_seed_is_idempotent(self):
        from django.core.management import call_command
        from io import StringIO
        call_command('seed_templates', stdout=StringIO())
        call_command('seed_templates', stdout=StringIO())
        self.assertEqual(ResumeTemplate.objects.count(), 5)


class PlanPremiumTemplatesFieldTests(TestCase):
    """Test the premium_templates field on Plan model."""

    def test_default_is_false(self):
        plan = Plan.objects.create(name='BasicPlan', slug='basic_plan', price=0)
        self.assertFalse(plan.premium_templates)

    def test_can_set_true(self):
        plan = Plan.objects.create(
            name='ProPlan', slug='pro_plan', price=999,
            premium_templates=True,
        )
        self.assertTrue(plan.premium_templates)
