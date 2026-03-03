"""
Tests for resume parsed_content — structured data on Resume/ResumeAnalysis.

Covers:
  - Pipeline integration — Phase B (STEP_RESUME_PARSE removed)
  - parsed_content on ResumeAnalysis model
  - Chat builder _prefill_from_resume fallback to parsed_content
  - Serializer inclusion of parsed_content

Note: parse_resume_text() tests removed in v0.36.0 — module deleted,
functionality merged into resume_understanding.py.
"""
import copy
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import Plan, Wallet
from analyzer.models import ResumeAnalysis, Resume, GeneratedResume, LLMResponse
from analyzer.services.resume_chat_service import _prefill_from_resume, _empty_resume_data


# ── Helpers ──────────────────────────────────────────────────────────────

def _ensure_free_plan():
    Plan.objects.get_or_create(
        slug='free',
        defaults={
            'name': 'Free', 'billing_cycle': 'free', 'price': 0,
            'credits_per_month': 2,
        },
    )


def _give_credits(user, amount=100):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet.balance = amount
    wallet.save(update_fields=['balance'])


def _make_pdf(content=b'%PDF-1.4 fake content'):
    return SimpleUploadedFile('resume.pdf', content, content_type='application/pdf')


SAMPLE_PARSED_CONTENT = {
    'contact': {
        'name': 'Jane Smith',
        'email': 'jane@example.com',
        'phone': '+1-555-0200',
        'location': 'New York, NY',
        'linkedin': 'https://linkedin.com/in/janesmith',
        'portfolio': 'https://janesmith.dev',
    },
    'summary': 'Full-stack developer with 5 years of experience in Python and React.',
    'experience': [
        {
            'title': 'Software Engineer',
            'company': 'WebCo',
            'location': 'Remote',
            'start_date': 'Jan 2020',
            'end_date': 'Present',
            'bullets': [
                'Built REST APIs serving 10M+ requests/day',
                'Led migration from monolith to microservices',
            ],
        },
    ],
    'education': [
        {
            'degree': 'B.S. Computer Science',
            'institution': 'MIT',
            'location': 'Cambridge, MA',
            'year': '2019',
            'gpa': '3.8',
        },
    ],
    'skills': {
        'technical': ['Python', 'JavaScript', 'React', 'Django'],
        'tools': ['Docker', 'AWS', 'Git'],
        'soft': ['Leadership', 'Communication'],
    },
    'certifications': [
        {
            'name': 'AWS Solutions Architect',
            'issuer': 'Amazon',
            'year': '2022',
        },
    ],
    'projects': [
        {
            'name': 'OpenSource CLI',
            'description': 'A CLI tool for managing deployments',
            'technologies': ['Python', 'Click'],
            'url': 'https://github.com/jane/cli',
        },
    ],
}

SAMPLE_RESUME_TEXT = """
JANE SMITH
jane@example.com | +1-555-0200 | New York, NY
LinkedIn: https://linkedin.com/in/janesmith | Portfolio: https://janesmith.dev

PROFESSIONAL SUMMARY
Full-stack developer with 5 years of experience in Python and React.

WORK EXPERIENCE
Software Engineer | WebCo | Remote
Jan 2020 - Present
- Built REST APIs serving 10M+ requests/day
- Led migration from monolith to microservices

EDUCATION
B.S. Computer Science | MIT | Cambridge, MA | 2019 | GPA: 3.8

SKILLS
Technical: Python, JavaScript, React, Django
Tools: Docker, AWS, Git
Soft Skills: Leadership, Communication

CERTIFICATIONS
AWS Solutions Architect | Amazon | 2022

PROJECTS
OpenSource CLI - A CLI tool for managing deployments
Technologies: Python, Click
https://github.com/jane/cli
"""


def _create_analysis(user, with_parsed=False, with_resume_text=True):
    """Helper to create a ResumeAnalysis for testing."""
    resume = Resume.objects.create(
        user=user,
        file=_make_pdf(),
        file_hash=uuid.uuid4().hex,
        original_filename='resume.pdf',
    )
    analysis = ResumeAnalysis.objects.create(
        user=user,
        resume_file=_make_pdf(),
        resume=resume,
        resume_text=SAMPLE_RESUME_TEXT if with_resume_text else '',
        jd_input_type='text',
        jd_text='Software Engineer role',
        resolved_jd='Software Engineer role',
        status=ResumeAnalysis.STATUS_DONE,
        pipeline_step=ResumeAnalysis.STEP_DONE,
        overall_grade='B',
        ats_score=75,
        parsed_content=copy.deepcopy(SAMPLE_PARSED_CONTENT) if with_parsed else None,
    )
    return resume, analysis


# ══════════════════════════════════════════════════════════════════════════════
# 1. parse_resume_text() tests — REMOVED in v0.36.0
#    Module resume_parser.py deleted; functionality in resume_understanding.py
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# 2. Pipeline integration — Phase B: resume_parse step removed
# ══════════════════════════════════════════════════════════════════════════════

class PipelinePhaseB_Tests(TestCase):
    """Test pipeline after Phase B — STEP_RESUME_PARSE removed from _STEPS."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user('pipeuser', 'pipe@test.com', 'pw')

    def test_step_removed_from_pipeline(self):
        """STEP_RESUME_PARSE is no longer in the pipeline's _STEPS list."""
        from analyzer.services.analyzer import ResumeAnalyzer
        step_names = [s[0] for s in ResumeAnalyzer._STEPS]
        self.assertNotIn(ResumeAnalysis.STEP_RESUME_PARSE, step_names)

    def test_pipeline_has_4_steps(self):
        """Pipeline should have exactly 4 steps after Phase B."""
        from analyzer.services.analyzer import ResumeAnalyzer
        self.assertEqual(len(ResumeAnalyzer._STEPS), 4)
        expected = ['pdf_extract', 'jd_scrape', 'llm_call', 'parse_result']
        self.assertEqual([s[0] for s in ResumeAnalyzer._STEPS], expected)

    def test_resume_parse_treated_as_done(self):
        """pipeline_step='resume_parse' is treated as 'done' for crash recovery."""
        from analyzer.services.analyzer import ResumeAnalyzer
        self.assertIn(ResumeAnalysis.STEP_RESUME_PARSE, ResumeAnalyzer._COMPLETED_STEPS)

    def test_step_constant_still_exists_on_model(self):
        """STEP_RESUME_PARSE constant still exists for backward compat."""
        self.assertEqual(ResumeAnalysis.STEP_RESUME_PARSE, 'resume_parse')

    def test_parsed_content_copied_from_resume(self):
        """Analysis gets parsed_content from Resume model (Phase A/B)."""
        resume, analysis = _create_analysis(self.user, with_parsed=False)
        # Simulate Phase A: parsed_content on Resume
        resume.parsed_content = copy.deepcopy(SAMPLE_PARSED_CONTENT)
        resume.save(update_fields=['parsed_content'])

        # Simulate step_parse_result copying parsed_content
        from analyzer.services.analyzer import ResumeAnalyzer
        analyzer = ResumeAnalyzer()
        # _step_parse_result now copies parsed_content from Resume
        if not analysis.parsed_content and analysis.resume:
            resume_obj = analysis.resume
            if resume_obj.parsed_content:
                analysis.parsed_content = resume_obj.parsed_content
                analysis.save(update_fields=['parsed_content'])

        analysis.refresh_from_db()
        self.assertIsNotNone(analysis.parsed_content)
        self.assertEqual(analysis.parsed_content['contact']['name'], 'Jane Smith')


# ══════════════════════════════════════════════════════════════════════════════
# 3. Model tests — parsed_content field behavior
# ══════════════════════════════════════════════════════════════════════════════

class ParsedContentModelTests(TestCase):
    """Test parsed_content field on ResumeAnalysis."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user('modeluser', 'model@test.com', 'pw')

    def test_parsed_content_nullable(self):
        """parsed_content defaults to None."""
        _, analysis = _create_analysis(self.user, with_parsed=False)
        self.assertIsNone(analysis.parsed_content)

    def test_parsed_content_stores_json(self):
        """parsed_content stores and retrieves JSON data correctly."""
        _, analysis = _create_analysis(self.user, with_parsed=True)
        analysis.refresh_from_db()
        self.assertEqual(analysis.parsed_content['contact']['name'], 'Jane Smith')
        self.assertEqual(len(analysis.parsed_content['experience']), 1)

    def test_soft_delete_clears_parsed_content(self):
        """soft_delete() clears parsed_content."""
        _, analysis = _create_analysis(self.user, with_parsed=True)
        analysis.soft_delete()
        analysis.refresh_from_db()
        self.assertIsNone(analysis.parsed_content)

    def test_pipeline_step_resume_parse_exists(self):
        """STEP_RESUME_PARSE is a valid pipeline_step choice."""
        _, analysis = _create_analysis(self.user)
        analysis.pipeline_step = ResumeAnalysis.STEP_RESUME_PARSE
        analysis.save(update_fields=['pipeline_step'])
        analysis.refresh_from_db()
        self.assertEqual(analysis.pipeline_step, 'resume_parse')


# ══════════════════════════════════════════════════════════════════════════════
# 4. Chat builder pre-fill fallback to parsed_content
# ══════════════════════════════════════════════════════════════════════════════

class ChatBuilderParsedContentFallbackTests(TestCase):
    """Test _prefill_from_resume falls back to parsed_content."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user('chatuser', 'chat@test.com', 'pw')

    def test_prefill_uses_parsed_content_when_no_generated(self):
        """_prefill_from_resume uses parsed_content when no GeneratedResume exists."""
        resume, analysis = _create_analysis(self.user, with_parsed=True)
        resume_data = _empty_resume_data()
        result = _prefill_from_resume(self.user, str(resume.id), resume_data)

        self.assertEqual(result['contact']['name'], 'Jane Smith')
        self.assertEqual(result['contact']['email'], 'jane@example.com')
        self.assertEqual(len(result['experience']), 1)
        self.assertEqual(result['experience'][0]['company'], 'WebCo')

    def test_prefill_prefers_generated_over_parsed(self):
        """_prefill_from_resume prefers GeneratedResume over parsed_content."""
        resume, analysis = _create_analysis(self.user, with_parsed=True)

        # Create a GeneratedResume with different data
        gen_content = copy.deepcopy(SAMPLE_PARSED_CONTENT)
        gen_content['contact']['name'] = 'Generated Jane'
        GeneratedResume.objects.create(
            user=self.user,
            analysis=analysis,
            status=GeneratedResume.STATUS_DONE,
            resume_content=gen_content,
        )

        resume_data = _empty_resume_data()
        result = _prefill_from_resume(self.user, str(resume.id), resume_data)
        # Should use GeneratedResume, not parsed_content
        self.assertEqual(result['contact']['name'], 'Generated Jane')

    def test_prefill_falls_back_to_any_analysis_parsed(self):
        """_prefill_from_resume uses any user's analysis parsed_content."""
        resume, analysis = _create_analysis(self.user, with_parsed=True)
        resume_data = _empty_resume_data()

        # Pass a non-existent resume ID — should fall back to user's analyses
        result = _prefill_from_resume(self.user, str(uuid.uuid4()), resume_data)
        self.assertEqual(result['contact']['name'], 'Jane Smith')

    def test_prefill_without_parsed_falls_to_profile(self):
        """_prefill_from_resume falls to profile when no parsed/generated exists."""
        resume, analysis = _create_analysis(self.user, with_parsed=False)
        resume_data = _empty_resume_data()

        result = _prefill_from_resume(self.user, str(resume.id), resume_data)
        # Should fall back to profile — name from User model
        self.assertEqual(result['contact']['name'], 'chatuser')
        self.assertEqual(result['contact']['email'], 'chat@test.com')

    def test_prefill_ensures_all_keys(self):
        """Pre-filled data from parsed_content includes all required keys."""
        resume, analysis = _create_analysis(self.user, with_parsed=True)
        # Remove a key to test backfill
        pc = copy.deepcopy(SAMPLE_PARSED_CONTENT)
        del pc['projects']
        analysis.parsed_content = pc
        analysis.save(update_fields=['parsed_content'])

        resume_data = _empty_resume_data()
        result = _prefill_from_resume(self.user, str(resume.id), resume_data)
        self.assertIn('projects', result)
        self.assertEqual(result['projects'], [])


# ══════════════════════════════════════════════════════════════════════════════
# 5. Serializer includes parsed_content
# ══════════════════════════════════════════════════════════════════════════════

class ParsedContentSerializerTests(TestCase):
    """Test that parsed_content appears in API responses."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user('seruser', 'ser@test.com', 'pw')
        _give_credits(self.user)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_detail_serializer_includes_parsed_content(self):
        """Analysis detail endpoint returns parsed_content."""
        _, analysis = _create_analysis(self.user, with_parsed=True)

        resp = self.client.get(f'/api/v1/analyses/{analysis.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('parsed_content', resp.data)
        self.assertEqual(resp.data['parsed_content']['contact']['name'], 'Jane Smith')

    def test_detail_serializer_null_parsed_content(self):
        """Analysis detail endpoint returns null when no parsed_content."""
        _, analysis = _create_analysis(self.user, with_parsed=False)

        resp = self.client.get(f'/api/v1/analyses/{analysis.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('parsed_content', resp.data)
        self.assertIsNone(resp.data['parsed_content'])
