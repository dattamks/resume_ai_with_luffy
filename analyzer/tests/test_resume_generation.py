"""
Tests for Phase 10: Resume Generation from Analysis Report.

Covers:
  - build_rewrite_prompt() — all analysis fields included
  - validate_resume_output() — schema validation, defaults, errors
  - GenerateResumeView — 202, 402, 400 for non-done analysis
  - GeneratedResumeStatusView — polling
  - GeneratedResumeDownloadView — 302 redirect / 404
  - GeneratedResumeListView — list user's generated resumes
  - render_resume_pdf() — integration test from sample JSON
  - render_resume_docx() — integration test from sample JSON
"""
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import Plan, Wallet
from analyzer.models import ResumeAnalysis, Resume, GeneratedResume, LLMResponse


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


SAMPLE_RESUME_CONTENT = {
    'contact': {
        'name': 'John Doe',
        'email': 'john@example.com',
        'phone': '+1-555-0100',
        'location': 'San Francisco, CA',
        'linkedin': 'https://linkedin.com/in/johndoe',
        'portfolio': 'https://johndoe.dev',
    },
    'summary': (
        'Senior software engineer with 8 years of experience building '
        'scalable web applications. Expert in Python, Django, and cloud services.'
    ),
    'experience': [
        {
            'title': 'Senior Software Engineer',
            'company': 'TechCorp Inc.',
            'location': 'San Francisco, CA',
            'start_date': 'Jan 2020',
            'end_date': 'Present',
            'bullets': [
                'Led migration of monolithic application to microservices, reducing deploy time by 70%',
                'Designed and implemented RESTful APIs serving 10M+ requests/day',
                'Mentored team of 5 junior engineers, improving code quality metrics by 40%',
            ],
        },
        {
            'title': 'Software Engineer',
            'company': 'StartupXYZ',
            'location': 'Remote',
            'start_date': 'Jun 2017',
            'end_date': 'Dec 2019',
            'bullets': [
                'Built real-time analytics dashboard using React and WebSockets',
                'Reduced API response times by 60% through query optimization',
            ],
        },
    ],
    'education': [
        {
            'degree': 'B.S. Computer Science',
            'institution': 'University of California, Berkeley',
            'location': 'Berkeley, CA',
            'year': '2017',
            'gpa': '3.8',
        },
    ],
    'skills': {
        'technical': ['Python', 'Django', 'PostgreSQL', 'AWS', 'Docker', 'Kubernetes'],
        'tools': ['Git', 'Jenkins', 'Terraform', 'Datadog'],
        'soft': ['Leadership', 'Mentoring', 'Communication'],
    },
    'certifications': [
        {
            'name': 'AWS Solutions Architect',
            'issuer': 'Amazon Web Services',
            'year': '2022',
        },
    ],
    'projects': [
        {
            'name': 'OpenSource CLI Tool',
            'description': 'Command-line tool for automated code review with 500+ GitHub stars',
            'technologies': ['Python', 'Click', 'OpenAI API'],
            'url': 'https://github.com/johndoe/cli-tool',
        },
    ],
}


def _create_done_analysis(user, **overrides):
    """Create a completed analysis with realistic data for testing."""
    defaults = {
        'user': user,
        'resume_file': 'resumes/test.pdf',
        'jd_input_type': ResumeAnalysis.JD_INPUT_TEXT,
        'jd_text': 'Senior Python Developer at TechCorp...',
        'status': ResumeAnalysis.STATUS_DONE,
        'resume_text': 'John Doe\nSenior Software Engineer\nExperience...',
        'jd_role': 'Senior Python Developer',
        'jd_company': 'TechCorp',
        'jd_skills': 'Python, Django, AWS, Kubernetes',
        'jd_industry': 'Technology',
        'jd_experience_years': 5,
        'overall_grade': 'B',
        'ats_score': 72,
        'summary': 'Good resume with room for improvement.',
        'keyword_analysis': {
            'matched_keywords': ['Python', 'Django', 'AWS'],
            'missing_keywords': ['Kubernetes', 'CI/CD', 'Terraform'],
            'recommended_to_add': [
                'Add Kubernetes to skills section',
                'Mention CI/CD experience in TechCorp role',
            ],
        },
        'sentence_suggestions': [
            {
                'original': 'Worked on backend systems',
                'suggested': 'Architected and maintained backend microservices handling 10M+ daily requests',
                'reason': 'Quantify impact and use strong action verb',
            },
            {
                'original': 'Helped with deployment',
                'suggested': 'Led CI/CD pipeline implementation, reducing deployment time by 70%',
                'reason': 'Show leadership and measurable improvement',
            },
        ],
        'section_feedback': [
            {'section_name': 'Summary', 'score': 60, 'feedback': ['Too generic', 'Missing target role keywords']},
            {'section_name': 'Experience', 'score': 75, 'feedback': ['Good quantification']},
            {'section_name': 'Skills', 'score': 50, 'feedback': ['Missing key technologies', 'Not categorized']},
        ],
        'quick_wins': [
            {'priority': 1, 'action': 'Add a professional summary tailored to the role'},
            {'priority': 2, 'action': 'Group skills by category (Technical, Tools, Soft)'},
            {'priority': 3, 'action': 'Add Kubernetes and CI/CD to skills section'},
        ],
        'formatting_flags': [
            'Inconsistent date format',
            'Missing bullet points in experience section',
        ],
    }
    defaults.update(overrides)
    return ResumeAnalysis.all_objects.create(**defaults)


# ══════════════════════════════════════════════════════════════════════════
# 1. Unit tests for build_rewrite_prompt
# ══════════════════════════════════════════════════════════════════════════

class BuildRewritePromptTests(TestCase):
    """Test that build_rewrite_prompt includes all analysis fields."""

    def setUp(self):
        self.user = User.objects.create_user(username='promptuser', password='StrongPass123!')
        _ensure_free_plan()
        self.analysis = _create_done_analysis(self.user)

    def test_prompt_includes_resume_text(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('John Doe', prompt)
        self.assertIn('Senior Software Engineer', prompt)

    def test_prompt_includes_target_role_context(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Senior Python Developer', prompt)
        self.assertIn('TechCorp', prompt)
        self.assertIn('Python, Django, AWS, Kubernetes', prompt)
        self.assertIn('Technology', prompt)
        self.assertIn('5 years', prompt)

    def test_prompt_includes_missing_keywords(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Kubernetes', prompt)
        self.assertIn('CI/CD', prompt)
        self.assertIn('Terraform', prompt)

    def test_prompt_includes_recommended_placements(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Add Kubernetes to skills section', prompt)
        self.assertIn('Mention CI/CD experience in TechCorp role', prompt)

    def test_prompt_includes_sentence_suggestions(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Worked on backend systems', prompt)
        self.assertIn('Architected and maintained backend microservices', prompt)
        self.assertIn('Quantify impact', prompt)

    def test_prompt_includes_section_feedback_below_70(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        # Summary (score 60) and Skills (score 50) are below 70
        self.assertIn('Summary (score: 60)', prompt)
        self.assertIn('Too generic', prompt)
        self.assertIn('Skills (score: 50)', prompt)
        self.assertIn('Missing key technologies', prompt)

    def test_prompt_excludes_section_feedback_above_70(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        # Experience (score 75) should NOT appear in weak sections
        # Check that the line "Experience (score: 75)" is not there
        self.assertNotIn('Experience (score: 75)', prompt)

    def test_prompt_includes_quick_wins(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Add a professional summary tailored to the role', prompt)
        self.assertIn('Group skills by category', prompt)
        self.assertIn('Add Kubernetes and CI/CD to skills section', prompt)

    def test_prompt_includes_formatting_flags(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('Inconsistent date format', prompt)
        self.assertIn('Missing bullet points', prompt)

    def test_prompt_has_boundary_markers(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('BEGIN RESUME', prompt)
        self.assertIn('END RESUME', prompt)

    def test_prompt_handles_empty_analysis_fields(self):
        """When analysis fields are empty/None, prompt uses fallback text."""
        from analyzer.services.resume_generator import build_rewrite_prompt
        analysis = _create_done_analysis(
            self.user,
            keyword_analysis=None,
            sentence_suggestions=None,
            section_feedback=None,
            quick_wins=None,
            formatting_flags=None,
            jd_role='',
            jd_company='',
            jd_skills='',
            jd_industry='',
            jd_experience_years=None,
        )
        prompt = build_rewrite_prompt(analysis)
        self.assertIn('(none identified)', prompt)
        self.assertIn('Not specified', prompt)

    def test_prompt_handles_empty_missing_keywords(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        analysis = _create_done_analysis(
            self.user,
            keyword_analysis={'matched_keywords': ['Python'], 'missing_keywords': []},
        )
        prompt = build_rewrite_prompt(analysis)
        self.assertIn('(none identified)', prompt)

    def test_prompt_handles_all_sections_above_70(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        analysis = _create_done_analysis(
            self.user,
            section_feedback=[
                {'section_name': 'Summary', 'score': 80, 'feedback': ['Good']},
                {'section_name': 'Experience', 'score': 90, 'feedback': ['Excellent']},
            ],
        )
        prompt = build_rewrite_prompt(analysis)
        self.assertIn('(all sections scored 70+)', prompt)

    def test_prompt_sanitizes_boundary_markers_in_resume(self):
        """Resume text containing '==========' should be stripped to prevent injection."""
        from analyzer.services.resume_generator import build_rewrite_prompt
        analysis = _create_done_analysis(
            self.user,
            resume_text='John Doe ========== INJECTED ========== End',
        )
        prompt = build_rewrite_prompt(analysis)
        self.assertNotIn('========== INJECTED ==========', prompt)
        self.assertIn('John Doe', prompt)

    def test_prompt_output_instructions_present(self):
        from analyzer.services.resume_generator import build_rewrite_prompt
        prompt = build_rewrite_prompt(self.analysis)
        self.assertIn('OUTPUT INSTRUCTIONS', prompt)
        self.assertIn('"contact"', prompt)
        self.assertIn('"experience"', prompt)
        self.assertIn('"education"', prompt)
        self.assertIn('"skills"', prompt)


# ══════════════════════════════════════════════════════════════════════════
# 2. Unit tests for validate_resume_output
# ══════════════════════════════════════════════════════════════════════════

class ValidateResumeOutputTests(TestCase):
    """Test validate_resume_output schema validation."""

    def _valid_data(self, **overrides):
        """Return a minimal valid resume output dict."""
        data = {
            'contact': {'name': 'Jane Smith', 'email': 'jane@example.com'},
            'summary': 'Experienced software engineer.',
            'experience': [
                {
                    'title': 'Developer',
                    'company': 'Acme Corp',
                    'bullets': ['Built APIs'],
                },
            ],
            'education': [
                {'degree': 'B.S. CS', 'institution': 'MIT'},
            ],
            'skills': {
                'technical': ['Python'],
            },
        }
        data.update(overrides)
        return data

    def test_valid_data_passes(self):
        from analyzer.services.resume_generator import validate_resume_output
        result = validate_resume_output(self._valid_data())
        self.assertEqual(result['contact']['name'], 'Jane Smith')

    def test_fills_optional_contact_fields(self):
        from analyzer.services.resume_generator import validate_resume_output
        result = validate_resume_output(self._valid_data())
        self.assertEqual(result['contact']['phone'], '')
        self.assertEqual(result['contact']['location'], '')
        self.assertEqual(result['contact']['linkedin'], '')
        self.assertEqual(result['contact']['portfolio'], '')

    def test_fills_optional_experience_fields(self):
        from analyzer.services.resume_generator import validate_resume_output
        result = validate_resume_output(self._valid_data())
        exp = result['experience'][0]
        self.assertEqual(exp['location'], '')
        self.assertEqual(exp['start_date'], '')
        self.assertEqual(exp['end_date'], '')

    def test_fills_optional_skills_categories(self):
        from analyzer.services.resume_generator import validate_resume_output
        result = validate_resume_output(self._valid_data())
        self.assertEqual(result['skills']['tools'], [])
        self.assertEqual(result['skills']['soft'], [])

    def test_fills_optional_arrays(self):
        from analyzer.services.resume_generator import validate_resume_output
        result = validate_resume_output(self._valid_data())
        self.assertEqual(result['certifications'], [])
        self.assertEqual(result['projects'], [])

    def test_fills_certification_defaults(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(certifications=[{'name': 'AWS'}])
        result = validate_resume_output(data)
        cert = result['certifications'][0]
        self.assertEqual(cert['issuer'], '')
        self.assertEqual(cert['year'], '')

    def test_fills_project_defaults(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(projects=[{'name': 'MyProject'}])
        result = validate_resume_output(data)
        proj = result['projects'][0]
        self.assertEqual(proj['description'], '')
        self.assertEqual(proj['technologies'], [])
        self.assertEqual(proj['url'], '')

    def test_fills_education_defaults(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(education=[{}])
        result = validate_resume_output(data)
        edu = result['education'][0]
        self.assertEqual(edu['degree'], '')
        self.assertEqual(edu['institution'], '')
        self.assertEqual(edu['location'], '')
        self.assertEqual(edu['year'], '')
        self.assertEqual(edu['gpa'], '')

    # ── Error cases ──

    def test_missing_contact_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data()
        del data['contact']
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('contact', str(ctx.exception))

    def test_missing_summary_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data()
        del data['summary']
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('summary', str(ctx.exception))

    def test_missing_experience_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data()
        del data['experience']
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('experience', str(ctx.exception))

    def test_missing_education_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data()
        del data['education']
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('education', str(ctx.exception))

    def test_missing_skills_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data()
        del data['skills']
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('skills', str(ctx.exception))

    def test_wrong_type_contact_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(contact='not a dict')
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('expected dict', str(ctx.exception))

    def test_wrong_type_experience_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(experience='not a list')
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('expected list', str(ctx.exception))

    def test_wrong_type_summary_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(summary=123)
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('expected str', str(ctx.exception))

    def test_empty_contact_name_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(contact={'name': '', 'email': 'a@b.com'})
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('contact.name', str(ctx.exception))

    def test_missing_contact_name_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(contact={'email': 'a@b.com'})
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('contact.name', str(ctx.exception))

    def test_experience_entry_not_dict_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(experience=['not a dict'])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('experience[0]', str(ctx.exception))

    def test_experience_missing_title_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(experience=[{'company': 'Acme'}])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('experience[0].title', str(ctx.exception))

    def test_experience_missing_company_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(experience=[{'title': 'Dev'}])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('experience[0].company', str(ctx.exception))

    def test_certification_not_dict_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(certifications=['not a dict'])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('certifications[0]', str(ctx.exception))

    def test_project_not_dict_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(projects=['not a dict'])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('projects[0]', str(ctx.exception))

    def test_education_not_dict_raises(self):
        from analyzer.services.resume_generator import validate_resume_output
        data = self._valid_data(education=['not a dict'])
        with self.assertRaises(ValueError) as ctx:
            validate_resume_output(data)
        self.assertIn('education[0]', str(ctx.exception))

    def test_valid_full_content_passes(self):
        """Full SAMPLE_RESUME_CONTENT should pass validation."""
        from analyzer.services.resume_generator import validate_resume_output
        import copy
        result = validate_resume_output(copy.deepcopy(SAMPLE_RESUME_CONTENT))
        self.assertEqual(result['contact']['name'], 'John Doe')
        self.assertEqual(len(result['experience']), 2)
        self.assertEqual(len(result['certifications']), 1)
        self.assertEqual(len(result['projects']), 1)


# ══════════════════════════════════════════════════════════════════════════
# 3. API endpoint tests
# ══════════════════════════════════════════════════════════════════════════

class GenerateResumeViewTests(TestCase):
    """Tests for POST /api/analyses/<id>/generate-resume/"""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user(username='genuser', password='StrongPass123!')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.analysis = _create_done_analysis(self.user)
        _give_credits(self.user, 100)
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('analyzer.views.generate_improved_resume_task')
    def test_generate_returns_202(self, mock_task):
        """Successful generation request returns 202."""
        mock_task.delay = MagicMock()
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('id', resp.data)
        self.assertEqual(resp.data['status'], 'pending')
        self.assertEqual(resp.data['template'], 'ats_classic')
        self.assertEqual(resp.data['format'], 'pdf')
        mock_task.delay.assert_called_once()

    @patch('analyzer.views.generate_improved_resume_task')
    def test_generate_uses_defaults(self, mock_task):
        """If template/format not provided, defaults are used."""
        mock_task.delay = MagicMock()
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/', {},
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['template'], 'ats_classic')
        self.assertEqual(resp.data['format'], 'pdf')

    @patch('analyzer.views.generate_improved_resume_task')
    def test_generate_docx_format(self, mock_task):
        """DOCX format accepted."""
        mock_task.delay = MagicMock()
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'format': 'docx'},
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['format'], 'docx')

    def test_generate_402_insufficient_credits(self):
        """Returns 402 when user has no credits."""
        _give_credits(self.user, 0)
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertIn('Insufficient credits', resp.data['detail'])
        self.assertIn('balance', resp.data)
        self.assertIn('cost', resp.data)

    def test_generate_400_analysis_not_done(self):
        """Returns 400 when analysis is not in 'done' status."""
        pending_analysis = _create_done_analysis(
            self.user, status=ResumeAnalysis.STATUS_PENDING,
        )
        resp = self.client.post(
            f'/api/analyses/{pending_analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must be complete', resp.data['detail'])

    def test_generate_400_analysis_processing(self):
        """Returns 400 when analysis is still processing."""
        processing = _create_done_analysis(
            self.user, status=ResumeAnalysis.STATUS_PROCESSING,
        )
        resp = self.client.post(
            f'/api/analyses/{processing.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_400_analysis_failed(self):
        """Returns 400 when analysis has failed."""
        failed = _create_done_analysis(
            self.user, status=ResumeAnalysis.STATUS_FAILED,
        )
        resp = self.client.post(
            f'/api/analyses/{failed.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_404_other_user(self):
        """Cannot generate for another user's analysis."""
        other = User.objects.create_user(username='otheruser', password='StrongPass123!')
        analysis = _create_done_analysis(other)
        resp = self.client.post(
            f'/api/analyses/{analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_generate_404_nonexistent(self):
        """Returns 404 for a nonexistent analysis ID."""
        resp = self.client.post(
            '/api/analyses/999999/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_generate_400_invalid_template(self):
        """Returns 400 for unsupported template slug."""
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'nonexistent_template', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_400_invalid_format(self):
        """Returns 400 for unsupported output format."""
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'html'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_requires_auth(self):
        """Unauthenticated requests are rejected."""
        anon_client = APIClient()
        resp = anon_client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertIn(resp.status_code, [401, 403])

    @patch('analyzer.views.generate_improved_resume_task')
    def test_generate_deducts_credits(self, mock_task):
        """Credits are deducted on successful generation."""
        mock_task.delay = MagicMock()
        _give_credits(self.user, 10)
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 9)  # 10 - 1 credit

    @patch('analyzer.views.generate_improved_resume_task')
    def test_generate_creates_record(self, mock_task):
        """A GeneratedResume record is created."""
        mock_task.delay = MagicMock()
        resp = self.client.post(
            f'/api/analyses/{self.analysis.pk}/generate-resume/',
            {'template': 'ats_classic', 'format': 'pdf'},
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        gen = GeneratedResume.objects.get(id=resp.data['id'])
        self.assertEqual(gen.analysis, self.analysis)
        self.assertEqual(gen.user, self.user)
        self.assertEqual(gen.template, 'ats_classic')
        self.assertEqual(gen.format, 'pdf')
        self.assertEqual(gen.status, GeneratedResume.STATUS_PENDING)
        self.assertTrue(gen.credits_deducted)


class GeneratedResumeStatusViewTests(TestCase):
    """Tests for GET /api/analyses/<id>/generated-resume/ (polling)."""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user(username='polluser', password='StrongPass123!')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.analysis = _create_done_analysis(self.user)

    def test_poll_returns_latest_generation(self):
        """Returns the most recent generated resume."""
        gen = GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['id'], str(gen.id))
        self.assertEqual(resp.data['status'], 'done')

    def test_poll_pending_status(self):
        """Returns pending status while generation is in progress."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_PENDING,
        )
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'pending')

    def test_poll_processing_status(self):
        """Returns processing status while LLM is working."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_PROCESSING,
        )
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'processing')

    def test_poll_failed_status_includes_error(self):
        """Failed status includes error message."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_FAILED,
            error_message='LLM returned invalid JSON',
        )
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], 'failed')
        self.assertEqual(resp.data['error_message'], 'LLM returned invalid JSON')

    def test_poll_404_no_generation(self):
        """Returns 404 when no generation exists."""
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_poll_404_other_user(self):
        """Cannot poll another user's analysis."""
        other = User.objects.create_user(username='otheruser2', password='StrongPass123!')
        other_analysis = _create_done_analysis(other)
        GeneratedResume.objects.create(
            analysis=other_analysis, user=other,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        resp = self.client.get(f'/api/analyses/{other_analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_poll_returns_file_url_when_done(self):
        """When done, file_url is present in response."""
        gen = GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        gen.file.save('test.pdf', ContentFile(b'%PDF-1.4 fake'), save=True)
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(resp.data['file_url'])

    def test_poll_file_url_null_when_pending(self):
        """file_url is null when generation is not done."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_PENDING,
        )
        resp = self.client.get(f'/api/analyses/{self.analysis.pk}/generated-resume/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data['file_url'])


class GeneratedResumeDownloadViewTests(TestCase):
    """Tests for GET /api/analyses/<id>/generated-resume/download/"""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user(username='dluser', password='StrongPass123!')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.analysis = _create_done_analysis(self.user)

    def test_download_redirects_when_done(self):
        """Returns 302 redirect when file is available."""
        gen = GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        gen.file.save('test.pdf', ContentFile(b'%PDF-1.4 fake'), save=True)
        resp = self.client.get(
            f'/api/analyses/{self.analysis.pk}/generated-resume/download/',
        )
        self.assertEqual(resp.status_code, status.HTTP_302_FOUND)

    def test_download_404_no_file(self):
        """Returns 404 when no file is available."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_PENDING,
        )
        resp = self.client.get(
            f'/api/analyses/{self.analysis.pk}/generated-resume/download/',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_404_no_generation(self):
        """Returns 404 when no generation exists at all."""
        resp = self.client.get(
            f'/api/analyses/{self.analysis.pk}/generated-resume/download/',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_404_other_user(self):
        """Cannot download another user's generated resume."""
        other = User.objects.create_user(username='otheruser3', password='StrongPass123!')
        other_analysis = _create_done_analysis(other)
        gen = GeneratedResume.objects.create(
            analysis=other_analysis, user=other,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        gen.file.save('test.pdf', ContentFile(b'%PDF-1.4 fake'), save=True)
        resp = self.client.get(
            f'/api/analyses/{other_analysis.pk}/generated-resume/download/',
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class GeneratedResumeListViewTests(TestCase):
    """Tests for GET /api/generated-resumes/"""

    def setUp(self):
        _ensure_free_plan()
        self.user = User.objects.create_user(username='listuser', password='StrongPass123!')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.analysis = _create_done_analysis(self.user)

    def test_list_returns_user_resumes(self):
        """Returns all generated resumes for the user."""
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='docx',
            status=GeneratedResume.STATUS_PENDING,
        )
        resp = self.client.get('/api/generated-resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_list_excludes_other_users(self):
        """Other users' generated resumes are not visible."""
        other = User.objects.create_user(username='otheruser4', password='StrongPass123!')
        other_analysis = _create_done_analysis(other)
        GeneratedResume.objects.create(
            analysis=other_analysis, user=other,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        resp = self.client.get('/api/generated-resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_list_empty(self):
        """Returns empty list when no generations exist."""
        resp = self.client.get('/api/generated-resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

    def test_list_ordered_by_newest_first(self):
        """Results are ordered by created_at descending."""
        gen1 = GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='pdf',
            status=GeneratedResume.STATUS_DONE,
        )
        gen2 = GeneratedResume.objects.create(
            analysis=self.analysis, user=self.user,
            template='ats_classic', format='docx',
            status=GeneratedResume.STATUS_DONE,
        )
        resp = self.client.get('/api/generated-resumes/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # gen2 was created after gen1, should be first
        self.assertEqual(resp.data[0]['id'], str(gen2.id))
        self.assertEqual(resp.data[1]['id'], str(gen1.id))

    def test_list_requires_auth(self):
        """Unauthenticated requests are rejected."""
        anon_client = APIClient()
        resp = anon_client.get('/api/generated-resumes/')
        self.assertIn(resp.status_code, [401, 403])


# ══════════════════════════════════════════════════════════════════════════
# 4. Integration tests for PDF and DOCX rendering
# ══════════════════════════════════════════════════════════════════════════

class RenderResumePDFTests(TestCase):
    """Integration tests for render_resume_pdf with sample structured JSON."""

    def test_render_produces_valid_pdf_bytes(self):
        """render_resume_pdf returns bytes starting with PDF magic number."""
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        pdf_bytes = render_resume_pdf(SAMPLE_RESUME_CONTENT)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 100)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_render_with_minimal_content(self):
        """PDF renders with minimal resume content."""
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        minimal = {
            'contact': {'name': 'Test User'},
            'summary': 'A developer.',
            'experience': [],
            'education': [],
            'skills': {'technical': [], 'tools': [], 'soft': []},
            'certifications': [],
            'projects': [],
        }
        pdf_bytes = render_resume_pdf(minimal)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_render_with_full_content(self):
        """PDF renders with complete resume content including all sections."""
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        pdf_bytes = render_resume_pdf(SAMPLE_RESUME_CONTENT)
        self.assertTrue(len(pdf_bytes) > 500)

    def test_render_with_empty_optional_sections(self):
        """PDF renders when certifications and projects are empty."""
        import copy
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        data = copy.deepcopy(SAMPLE_RESUME_CONTENT)
        data['certifications'] = []
        data['projects'] = []
        pdf_bytes = render_resume_pdf(data)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_render_with_special_characters(self):
        """PDF handles special characters (XML entities, unicode) without crashing."""
        import copy
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        data = copy.deepcopy(SAMPLE_RESUME_CONTENT)
        data['contact']['name'] = 'John "O\'Brien" Doe & Partners'
        data['summary'] = 'Expert in C++ / C# with <10 years exp. Uses "quotes" & ampersands.'
        data['experience'][0]['bullets'] = [
            'Used <script>alert("xss")</script> to test security',
            'Revenue grew 200% → $5M ARR',
        ]
        pdf_bytes = render_resume_pdf(data)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

    def test_render_with_many_experience_entries(self):
        """PDF handles many experience entries (multi-page resume)."""
        import copy
        from analyzer.services.resume_pdf_renderer import render_resume_pdf
        data = copy.deepcopy(SAMPLE_RESUME_CONTENT)
        data['experience'] = [
            {
                'title': f'Role {i}',
                'company': f'Company {i}',
                'location': 'Remote',
                'start_date': f'Jan 20{10+i}',
                'end_date': f'Dec 20{10+i}',
                'bullets': [f'Achievement {j} for role {i}' for j in range(5)],
            }
            for i in range(10)
        ]
        pdf_bytes = render_resume_pdf(data)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(len(pdf_bytes) > 1000)


class RenderResumeDOCXTests(TestCase):
    """Integration tests for render_resume_docx with sample structured JSON."""

    def test_render_produces_valid_docx_bytes(self):
        """render_resume_docx returns bytes with DOCX magic number (PK zip)."""
        from analyzer.services.resume_docx_renderer import render_resume_docx
        docx_bytes = render_resume_docx(SAMPLE_RESUME_CONTENT)
        self.assertIsInstance(docx_bytes, bytes)
        self.assertTrue(len(docx_bytes) > 100)
        # DOCX is a ZIP file — starts with PK magic bytes
        self.assertTrue(docx_bytes[:2] == b'PK')

    def test_render_with_minimal_content(self):
        """DOCX renders with minimal resume content."""
        from analyzer.services.resume_docx_renderer import render_resume_docx
        minimal = {
            'contact': {'name': 'Test User'},
            'summary': 'A developer.',
            'experience': [],
            'education': [],
            'skills': {'technical': [], 'tools': [], 'soft': []},
            'certifications': [],
            'projects': [],
        }
        docx_bytes = render_resume_docx(minimal)
        self.assertIsInstance(docx_bytes, bytes)
        self.assertTrue(docx_bytes[:2] == b'PK')

    def test_render_with_full_content(self):
        """DOCX renders with complete resume content including all sections."""
        from analyzer.services.resume_docx_renderer import render_resume_docx
        docx_bytes = render_resume_docx(SAMPLE_RESUME_CONTENT)
        self.assertTrue(len(docx_bytes) > 500)

    def test_render_with_special_characters(self):
        """DOCX handles special characters without crashing."""
        import copy
        from analyzer.services.resume_docx_renderer import render_resume_docx
        data = copy.deepcopy(SAMPLE_RESUME_CONTENT)
        data['contact']['name'] = 'José García-López'
        data['summary'] = 'Expert in C++ / C# with <10 years exp. Uses "quotes" & ampersands.'
        docx_bytes = render_resume_docx(data)
        self.assertIsInstance(docx_bytes, bytes)
        self.assertTrue(docx_bytes[:2] == b'PK')
