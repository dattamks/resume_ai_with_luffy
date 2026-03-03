"""
Tests for auto-creation of Resume from GeneratedResume.

When a resume is generated (via analysis-based rewrite or chat builder),
the system auto-creates a full Resume record that can be used for:
  - New analyses
  - Job alerts
  - Feed / dashboard
  - Embedding-based matching

Covers:
  - _create_resume_from_generated() — happy path, dedup, error handling
  - _build_career_profile() — field extraction, seniority estimation
  - _resume_content_to_text() — plain text conversion
  - GeneratedResumeSerializer — includes resume field
  - Integration: generate_improved_resume_task chains auto-create
  - Integration: render_builder_resume_task chains auto-create
"""
import hashlib
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status as drf_status

from accounts.models import Plan, Wallet
from analyzer.models import (
    Resume, ResumeAnalysis, GeneratedResume, ResumeVersion,
    JobSearchProfile, LLMResponse, ResumeTemplate,
)


# ── Fixtures ─────────────────────────────────────────────────────────────

SAMPLE_RESUME_CONTENT = {
    'contact': {
        'name': 'Jane Smith',
        'email': 'jane@example.com',
        'phone': '+1-555-0199',
        'location': 'New York, NY',
        'linkedin': 'https://linkedin.com/in/janesmith',
    },
    'summary': 'Full-stack engineer with 6 years building scalable APIs.',
    'experience': [
        {
            'title': 'Senior Engineer',
            'company': 'BigCo',
            'location': 'New York, NY',
            'start_date': 'Jan 2021',
            'end_date': 'Present',
            'bullets': [
                'Designed event-driven architecture handling 5M events/day',
                'Led team of 4 on payment microservice rewrite',
            ],
        },
        {
            'title': 'Software Engineer',
            'company': 'StartupABC',
            'location': 'Remote',
            'start_date': 'Jun 2018',
            'end_date': 'Dec 2020',
            'bullets': [
                'Built REST APIs in Django serving 1M requests/day',
            ],
        },
        {
            'title': 'Junior Developer',
            'company': 'WebShop',
            'location': 'Boston, MA',
            'start_date': 'Jan 2017',
            'end_date': 'May 2018',
            'bullets': [
                'Developed frontend components in React',
            ],
        },
    ],
    'education': [
        {
            'degree': 'B.S. Computer Science',
            'institution': 'MIT',
            'year': '2016',
        },
    ],
    'skills': {
        'languages': ['Python', 'JavaScript', 'Go'],
        'frameworks': ['Django', 'React', 'FastAPI'],
        'tools': ['Docker', 'AWS', 'PostgreSQL'],
    },
    'certifications': [
        {'name': 'AWS Certified Developer', 'issuer': 'AWS', 'year': '2023'},
    ],
}


def _setup_user():
    """Create user with free plan and credits."""
    Plan.objects.get_or_create(
        slug='free',
        defaults={'name': 'Free', 'billing_cycle': 'free', 'price': 0, 'credits_per_month': 10},
    )
    user = User.objects.create_user('testuser', 'test@example.com', 'pass1234')
    Wallet.objects.get_or_create(user=user, defaults={'balance': 50})
    return user


def _create_analysis(user, **overrides):
    """Create a done analysis."""
    defaults = {
        'user': user,
        'resume_file': 'resumes/test.pdf',
        'jd_input_type': ResumeAnalysis.JD_INPUT_TEXT,
        'jd_text': 'Senior Python Developer at BigCo',
        'status': ResumeAnalysis.STATUS_DONE,
        'resume_text': 'Jane Smith\nSenior Engineer',
        'jd_role': 'Senior Python Developer',
        'jd_company': 'BigCo',
        'jd_skills': 'Python, Django, AWS',
        'overall_grade': 'B+',
        'ats_score': 78,
        'summary': 'Strong resume.',
    }
    defaults.update(overrides)
    return ResumeAnalysis.objects.create(**defaults)


def _ensure_template():
    ResumeTemplate.objects.get_or_create(
        slug='ats_classic',
        defaults={'name': 'ATS Classic', 'is_premium': False, 'is_active': True, 'sort_order': 0},
    )


# ── Unit tests for helper functions ─────────────────────────────────────

class BuildCareerProfileTest(TestCase):
    """Tests for _build_career_profile()."""

    def setUp(self):
        from analyzer.tasks import _build_career_profile
        self.build = _build_career_profile

    def test_basic_extraction(self):
        """Career profile extracts titles, skills, locations from resume_content."""
        analysis = MagicMock()
        analysis.jd_role = 'Senior Python Developer'
        profile = self.build(SAMPLE_RESUME_CONTENT, analysis)

        self.assertIn('Senior Python Developer', profile['titles'])
        self.assertIn('Senior Engineer', profile['titles'])
        self.assertIn('Python', profile['skills'])
        self.assertIn('Django', profile['skills'])
        self.assertIn('New York, NY', profile['locations'])

    def test_seniority_senior(self):
        """3 roles × 2 years = 6 → senior."""
        analysis = MagicMock()
        analysis.jd_role = 'Engineer'
        profile = self.build(SAMPLE_RESUME_CONTENT, analysis)
        self.assertEqual(profile['seniority'], 'senior')

    def test_seniority_junior(self):
        """1 role × 2 years = 2 → junior."""
        content = {
            'contact': {},
            'experience': [{'title': 'Intern', 'company': 'Foo'}],
            'skills': {},
        }
        profile = self.build(content, None)
        self.assertEqual(profile['seniority'], 'junior')

    def test_seniority_lead(self):
        """5+ roles × 2 years = 10+ → lead."""
        content = {
            'contact': {},
            'experience': [{'title': f'Role {i}', 'company': f'Co{i}'} for i in range(6)],
            'skills': {},
        }
        profile = self.build(content, None)
        self.assertEqual(profile['seniority'], 'lead')

    def test_skills_list_format(self):
        """Handle skills as a simple list (not dict)."""
        content = {
            'contact': {},
            'experience': [],
            'skills': ['Python', 'Go', 'Rust'],
        }
        profile = self.build(content, None)
        self.assertEqual(profile['skills'], ['Python', 'Go', 'Rust'])

    def test_no_analysis(self):
        """Works when analysis is None."""
        profile = self.build(SAMPLE_RESUME_CONTENT, None)
        self.assertNotIn(None, profile['titles'])
        self.assertIn('Senior Engineer', profile['titles'])

    def test_max_titles(self):
        """Titles capped at 5."""
        content = {
            'contact': {},
            'experience': [{'title': f'Title {i}', 'company': f'C{i}'} for i in range(10)],
            'skills': {},
        }
        profile = self.build(content, None)
        self.assertLessEqual(len(profile['titles']), 5)

    def test_max_skills(self):
        """Skills capped at 20."""
        content = {
            'contact': {},
            'experience': [],
            'skills': {f'cat{i}': [f's{j}' for j in range(10)] for i in range(5)},
        }
        profile = self.build(content, None)
        self.assertLessEqual(len(profile['skills']), 20)


class ResumeContentToTextTest(TestCase):
    """Tests for _resume_content_to_text()."""

    def setUp(self):
        from analyzer.tasks import _resume_content_to_text
        self.to_text = _resume_content_to_text

    def test_basic_text(self):
        """All major sections appear in the text."""
        text = self.to_text(SAMPLE_RESUME_CONTENT)
        self.assertIn('Jane Smith', text)
        self.assertIn('SUMMARY', text)
        self.assertIn('Full-stack engineer', text)
        self.assertIn('Senior Engineer', text)
        self.assertIn('BigCo', text)
        self.assertIn('EDUCATION', text)
        self.assertIn('B.S. Computer Science', text)
        self.assertIn('SKILLS', text)
        self.assertIn('Python', text)
        self.assertIn('AWS Certified Developer', text)

    def test_experience_bullets(self):
        """Bullets are included as indented list items."""
        text = self.to_text(SAMPLE_RESUME_CONTENT)
        self.assertIn('  - Designed event-driven architecture', text)

    def test_empty_content(self):
        """Handles empty resume_content gracefully."""
        text = self.to_text({})
        self.assertIsInstance(text, str)

    def test_skills_list_format(self):
        """Skills as a flat list still works."""
        content = {'skills': ['Python', 'Go']}
        text = self.to_text(content)
        self.assertIn('Python', text)
        self.assertIn('Go', text)


# ── Integration tests for _create_resume_from_generated ──────────────────

@override_settings(DEFAULT_FILE_STORAGE='django.core.files.storage.InMemoryStorage')
class CreateResumeFromGeneratedTest(TestCase):
    """Tests for _create_resume_from_generated()."""

    def setUp(self):
        self.user = _setup_user()
        self.analysis = _create_analysis(self.user)
        _ensure_template()

        self.gen = GeneratedResume.objects.create(
            user=self.user,
            analysis=self.analysis,
            template='ats_classic',
            format=GeneratedResume.FORMAT_PDF,
            resume_content=SAMPLE_RESUME_CONTENT,
            status=GeneratedResume.STATUS_DONE,
        )
        self.pdf_bytes = b'%PDF-1.4 test content for generated resume'

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_creates_resume_record(self, mock_embed):
        """A full Resume record is created with correct fields."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        self.assertIsNotNone(self.gen.resume)

        resume = self.gen.resume
        self.assertEqual(resume.user, self.user)
        self.assertEqual(resume.processing_status, Resume.PROCESSING_DONE)
        self.assertEqual(resume.parsed_content, SAMPLE_RESUME_CONTENT)
        self.assertIn('Jane Smith', resume.resume_text)
        self.assertIsNotNone(resume.career_profile)
        self.assertIn('titles', resume.career_profile)
        self.assertEqual(resume.file_size_bytes, len(self.pdf_bytes))

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_creates_resume_version(self, mock_embed):
        """ResumeVersion entry is created."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        versions = ResumeVersion.objects.filter(resume=self.gen.resume)
        self.assertEqual(versions.count(), 1)
        self.assertEqual(versions.first().version_number, 1)
        self.assertIn('ats_classic', versions.first().change_summary)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_creates_job_search_profile(self, mock_embed):
        """JobSearchProfile is created from career_profile."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        jsp = JobSearchProfile.objects.filter(resume=self.gen.resume).first()
        self.assertIsNotNone(jsp)
        self.assertIn('Senior Python Developer', jsp.titles)
        self.assertIn('Python', jsp.skills)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_sets_default_if_no_default(self, mock_embed):
        """Auto-sets as default if user has no default resume."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        self.assertTrue(self.gen.resume.is_default)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_does_not_override_existing_default(self, mock_embed):
        """Does not change existing default resume."""
        from analyzer.tasks import _create_resume_from_generated

        # Create an existing default resume
        existing = Resume.objects.create(
            user=self.user,
            file_hash='existing_hash_123',
            original_filename='existing.pdf',
            is_default=True,
            processing_status=Resume.PROCESSING_DONE,
        )
        existing.file.save('resumes/existing.pdf', ContentFile(b'existing'))

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        self.assertFalse(self.gen.resume.is_default)
        existing.refresh_from_db()
        self.assertTrue(existing.is_default)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_dedup_same_hash(self, mock_embed):
        """If same file hash already exists, links to existing Resume."""
        from analyzer.tasks import _create_resume_from_generated

        file_hash = hashlib.sha256(self.pdf_bytes).hexdigest()
        existing = Resume.objects.create(
            user=self.user,
            file_hash=file_hash,
            original_filename='dedup.pdf',
            processing_status=Resume.PROCESSING_DONE,
        )
        existing.file.save('resumes/dedup.pdf', ContentFile(self.pdf_bytes))

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        self.assertEqual(self.gen.resume_id, existing.id)
        # No new Resume created
        self.assertEqual(Resume.objects.filter(user=self.user).count(), 1)
        # Embedding not triggered for dedup
        mock_embed.delay.assert_not_called()

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_chains_embedding_task(self, mock_embed):
        """compute_resume_embedding_task is called for the new Resume."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        mock_embed.delay.assert_called_once_with(str(self.gen.resume_id))

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_docx_renders_pdf(self, mock_embed):
        """When format is DOCX, a PDF is rendered for the Resume file."""
        from analyzer.tasks import _create_resume_from_generated

        self.gen.format = GeneratedResume.FORMAT_DOCX
        self.gen.save(update_fields=['format'])

        with patch('analyzer.services.template_registry.get_renderer') as mock_renderer:
            mock_renderer.return_value = lambda content: b'%PDF-1.4 rendered from docx'
            _create_resume_from_generated(
                self.gen, SAMPLE_RESUME_CONTENT, b'DOCX raw bytes', 'docx',
            )

        self.gen.refresh_from_db()
        self.assertIsNotNone(self.gen.resume)
        # File should be a PDF, not DOCX
        self.assertTrue(self.gen.resume.original_filename.endswith('.pdf'))

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_best_effort_no_failure(self, mock_embed):
        """If _create_resume_from_generated raises, generation itself is still done."""
        from analyzer.tasks import _create_resume_from_generated

        # Force an error inside the function
        with patch('analyzer.tasks._build_career_profile', side_effect=RuntimeError('boom')):
            # Should NOT raise
            _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        # GeneratedResume is still done (status not changed to failed)
        self.gen.refresh_from_db()
        self.assertEqual(self.gen.status, GeneratedResume.STATUS_DONE)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_file_hash_correct(self, mock_embed):
        """Resume has the correct SHA-256 file hash."""
        from analyzer.tasks import _create_resume_from_generated

        expected_hash = hashlib.sha256(self.pdf_bytes).hexdigest()
        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        self.assertEqual(self.gen.resume.file_hash, expected_hash)

    @patch('analyzer.tasks.compute_resume_embedding_task')
    def test_original_filename_format(self, mock_embed):
        """Original filename includes contact name and role."""
        from analyzer.tasks import _create_resume_from_generated

        _create_resume_from_generated(self.gen, SAMPLE_RESUME_CONTENT, self.pdf_bytes, 'pdf')

        self.gen.refresh_from_db()
        fname = self.gen.resume.original_filename
        self.assertIn('Jane', fname)
        self.assertIn('generated.pdf', fname)


# ── Serializer test ──────────────────────────────────────────────────────

@override_settings(DEFAULT_FILE_STORAGE='django.core.files.storage.InMemoryStorage')
class GeneratedResumeSerializerTest(TestCase):
    """Ensure the serializer exposes the resume FK."""

    def test_resume_field_in_serializer(self):
        from analyzer.serializers import GeneratedResumeSerializer

        user = _setup_user()
        analysis = _create_analysis(user)
        gen = GeneratedResume.objects.create(
            user=user,
            analysis=analysis,
            template='ats_classic',
            format=GeneratedResume.FORMAT_PDF,
            status=GeneratedResume.STATUS_PENDING,
        )
        serializer = GeneratedResumeSerializer(gen)
        data = serializer.data
        self.assertIn('resume', data)
        self.assertIsNone(data['resume'])

    def test_resume_field_with_linked_resume(self):
        from analyzer.serializers import GeneratedResumeSerializer

        user = _setup_user()
        analysis = _create_analysis(user)
        resume = Resume.objects.create(
            user=user,
            file_hash='abc123',
            original_filename='test.pdf',
            processing_status=Resume.PROCESSING_DONE,
        )
        resume.file.save('resumes/test.pdf', ContentFile(b'test'))
        gen = GeneratedResume.objects.create(
            user=user,
            analysis=analysis,
            template='ats_classic',
            format=GeneratedResume.FORMAT_PDF,
            status=GeneratedResume.STATUS_DONE,
            resume=resume,
        )
        serializer = GeneratedResumeSerializer(gen)
        data = serializer.data
        self.assertEqual(str(data['resume']), str(resume.id))


# ── Integration: generate_improved_resume_task ───────────────────────────

@override_settings(DEFAULT_FILE_STORAGE='django.core.files.storage.InMemoryStorage')
class GenerateResumeTaskIntegrationTest(TestCase):
    """Test that generate_improved_resume_task auto-creates a Resume."""

    def setUp(self):
        self.user = _setup_user()
        self.analysis = _create_analysis(self.user)
        _ensure_template()

    @patch('analyzer.tasks.compute_resume_embedding_task')
    @patch('analyzer.services.template_registry.get_renderer')
    @patch('analyzer.services.resume_generator.call_llm_for_rewrite')
    def test_task_creates_linked_resume(self, mock_rewrite, mock_renderer, mock_embed):
        """Full task run ends with a linked Resume."""
        mock_rewrite.return_value = {
            'parsed': SAMPLE_RESUME_CONTENT,
            'prompt': 'test prompt',
            'raw': 'test raw',
            'model': 'gpt-4',
            'duration': 2.5,
        }
        mock_renderer.return_value = lambda content: b'%PDF-1.4 rendered'

        gen = GeneratedResume.objects.create(
            user=self.user,
            analysis=self.analysis,
            template='ats_classic',
            format=GeneratedResume.FORMAT_PDF,
            status=GeneratedResume.STATUS_PENDING,
            credits_deducted=True,
        )

        from analyzer.tasks import generate_improved_resume_task
        generate_improved_resume_task(str(gen.id))

        gen.refresh_from_db()
        self.assertEqual(gen.status, GeneratedResume.STATUS_DONE)
        self.assertIsNotNone(gen.resume)
        self.assertEqual(gen.resume.processing_status, Resume.PROCESSING_DONE)
        mock_embed.delay.assert_called_once()


# ── Integration: render_builder_resume_task ──────────────────────────────

@override_settings(DEFAULT_FILE_STORAGE='django.core.files.storage.InMemoryStorage')
class BuilderResumeTaskIntegrationTest(TestCase):
    """Test that render_builder_resume_task auto-creates a Resume."""

    def setUp(self):
        self.user = _setup_user()
        _ensure_template()

    @patch('analyzer.tasks.compute_resume_embedding_task')
    @patch('analyzer.services.template_registry.get_renderer')
    def test_builder_task_creates_linked_resume(self, mock_renderer, mock_embed):
        """Builder render task creates a linked Resume."""
        mock_renderer.return_value = lambda content: b'%PDF-1.4 builder output'

        gen = GeneratedResume.objects.create(
            user=self.user,
            analysis=None,  # builder resumes have no analysis
            template='ats_classic',
            format=GeneratedResume.FORMAT_PDF,
            resume_content=SAMPLE_RESUME_CONTENT,
            status=GeneratedResume.STATUS_PENDING,
            credits_deducted=True,
        )

        from analyzer.tasks import render_builder_resume_task
        render_builder_resume_task(str(gen.id))

        gen.refresh_from_db()
        self.assertEqual(gen.status, GeneratedResume.STATUS_DONE)
        self.assertIsNotNone(gen.resume)
        self.assertEqual(gen.resume.processing_status, Resume.PROCESSING_DONE)
        self.assertIn('Jane Smith', gen.resume.resume_text)
        mock_embed.delay.assert_called_once()
