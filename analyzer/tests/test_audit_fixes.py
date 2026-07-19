"""
Regression tests for the analyzer/AI/feed/ingest fixes from the audit.

Covered:
- Feed role-scoping returns a 4-tuple on the no-titles path (no 500 for new users)
- Monthly analysis quota counts soft-deleted analyses (no quota reset via delete)
- Cover-letter generation deducts credits when a cost is configured
- Crawler ingest rejects a wrong X-Crawler-Key (constant-time compare)
- NewsSnippet re-ingest under a new uuid but existing source_url doesn't 500
- section_name is read by cover-letter / interview-prep consumers
- PDF extractor raises friendly errors for encrypted / corrupt / oversized files
- Model cost estimation doesn't mis-price gpt-4o as gpt-4o-mini
"""
import uuid
from io import BytesIO
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import Plan, Wallet, CreditCost
from analyzer.models import ResumeAnalysis, DiscoveredJob, NewsSnippet


def _make_pdf(content=b'%PDF-1.4 hello world resume text'):
    f = BytesIO(content)
    f.name = 'resume.pdf'
    return f


class _AuthMixin:
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.free_plan = Plan.objects.create(
            name='Free', slug='free', billing_cycle='free', price=0,
            credits_per_month=2, max_credits_balance=10,
            analyses_per_month=0, max_resumes_stored=50,
            is_active=True, display_order=0,
        )
        self.user = User.objects.create_user(
            username='fixuser', email='fix@test.com', password='StrongPass123!',
        )
        resp = self.client.post('/api/v1/auth/login/', {
            'username': 'fixuser', 'password': 'StrongPass123!',
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {resp.data["access"]}')

    def _give_credits(self, amount=100):
        wallet, _ = Wallet.objects.get_or_create(user=self.user)
        wallet.balance = amount
        wallet.save(update_fields=['balance'])


class FeedRoleScopingTests(_AuthMixin, TestCase):
    def test_no_titles_path_returns_four_tuple(self):
        from analyzer.views_feed import _get_role_scoped_qs
        base_qs = DiscoveredJob.objects.all()
        result = _get_role_scoped_qs(self.user, base_qs)
        # Must be a 4-tuple; every caller unpacks (qs, info, is_scoped, role_qs).
        self.assertEqual(len(result), 4)
        qs, info, is_scoped, role_qs = result
        self.assertFalse(is_scoped)
        self.assertEqual(info['method'], 'none')

    def test_trending_skills_endpoint_no_500_for_new_user(self):
        resp = self.client.get('/api/v1/feed/trending-skills/')
        self.assertLess(resp.status_code, 500)


class QuotaSoftDeleteTests(_AuthMixin, TestCase):
    @patch('analyzer.views.process_resume_upload_task')
    @patch('analyzer.views.run_analysis_task')
    def test_soft_deleted_analyses_still_count_toward_quota(self, mock_task, mock_upload):
        mock_task.delay.return_value = MagicMock(id='t')
        mock_upload.delay.return_value = MagicMock()
        self._give_credits()
        # Plan with a monthly limit of 1.
        self.user.profile.plan = Plan.objects.create(
            name='Lim', slug='lim', billing_cycle='monthly', price=1,
            credits_per_month=100, max_credits_balance=1000,
            analyses_per_month=1, max_resumes_stored=50,
            is_active=True, display_order=5,
        )
        self.user.profile.save()

        # One analysis already used this month, then soft-deleted.
        a = ResumeAnalysis.objects.create(user=self.user, status=ResumeAnalysis.STATUS_DONE)
        a.soft_delete()

        resp = self.client.post('/api/v1/analyze/', {
            'resume_file': _make_pdf(), 'jd_input_type': 'text', 'jd_text': 'Python dev',
        }, format='multipart')
        # Quota must still be considered reached despite the soft-delete.
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class CoverLetterBillingTests(_AuthMixin, TestCase):
    @patch('analyzer.views.generate_cover_letter_task')
    def test_cover_letter_deducts_configured_credits(self, mock_task):
        mock_task.delay.return_value = MagicMock()
        CreditCost.objects.update_or_create(action='cover_letter', defaults={'cost': 1})
        self._give_credits(5)
        analysis = ResumeAnalysis.objects.create(
            user=self.user, status=ResumeAnalysis.STATUS_DONE, jd_role='SWE',
        )
        resp = self.client.post(f'/api/v1/analyses/{analysis.id}/cover-letter/',
                                {'tone': 'professional'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(Wallet.objects.get(user=self.user).balance, 4)

    @patch('analyzer.views.generate_cover_letter_task')
    def test_cover_letter_insufficient_credits(self, mock_task):
        mock_task.delay.return_value = MagicMock()
        CreditCost.objects.update_or_create(action='cover_letter', defaults={'cost': 5})
        self._give_credits(0)
        analysis = ResumeAnalysis.objects.create(
            user=self.user, status=ResumeAnalysis.STATUS_DONE, jd_role='SWE',
        )
        resp = self.client.post(f'/api/v1/analyses/{analysis.id}/cover-letter/',
                                {'tone': 'professional'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_402_PAYMENT_REQUIRED)


@override_settings(CRAWLER_API_KEY='secret-crawler-key')
class IngestAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_wrong_key_rejected(self):
        resp = self.client.post('/api/v1/ingest/ping/', {}, format='json',
                                HTTP_X_CRAWLER_KEY='wrong-key')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_correct_key_accepted(self):
        resp = self.client.get('/api/v1/ingest/ping/',
                               HTTP_X_CRAWLER_KEY='secret-crawler-key')
        self.assertLess(resp.status_code, 400)


class NewsSnippetDedupTests(TestCase):
    def _payload(self, snippet_uuid, url):
        return {
            'uuid': str(snippet_uuid),
            'headline': 'Big hiring news',
            'summary': 'A company is hiring a lot of engineers.',
            'source_url': url,
            'category': NewsSnippet.CATEGORY_HIRING,
        }

    def test_new_uuid_same_source_url_merges_without_integrity_error(self):
        from analyzer.serializers_ingest import NewsSnippetIngestSerializer
        url = 'https://news.example.com/article-1'

        s1 = NewsSnippetIngestSerializer(data=self._payload(uuid.uuid4(), url))
        s1.is_valid(raise_exception=True)
        s1.save()

        # Same article re-crawled under a fresh uuid — must not raise.
        s2 = NewsSnippetIngestSerializer(data=self._payload(uuid.uuid4(), url))
        s2.is_valid(raise_exception=True)
        s2.save()

        self.assertEqual(NewsSnippet.objects.filter(source_url=url).count(), 1)


class SectionNameConsumerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='snuser', password='StrongPass123!')

    def _analysis(self, section_feedback):
        return ResumeAnalysis.objects.create(
            user=self.user, status=ResumeAnalysis.STATUS_DONE,
            jd_role='SWE', jd_company='Co', jd_industry='Tech',
            overall_grade='B', ats_score=80, summary='Strong.',
            resume_text='Experienced engineer.',
            keyword_analysis={'matched_keywords': ['python'], 'missing_keywords': ['go']},
            section_feedback=section_feedback,
        )

    def test_cover_letter_prompt_reads_section_name(self):
        from analyzer.services.cover_letter import build_cover_letter_prompt
        analysis = self._analysis([
            {'section_name': 'Work Experience', 'score': 90, 'feedback': []},
        ])
        prompt = build_cover_letter_prompt(analysis)
        self.assertIn('Work Experience', prompt)
        self.assertNotIn('- Unknown (Score: 90)', prompt)

    def test_interview_prompt_reads_section_name(self):
        from analyzer.services.interview_prep import build_interview_prep_prompt
        analysis = self._analysis([
            {'section_name': 'Skills', 'score': 40, 'feedback': ['thin']},
        ])
        prompt = build_interview_prep_prompt(analysis)
        self.assertIn('Skills', prompt)


class PDFExtractorTests(TestCase):
    def test_corrupt_pdf_raises_value_error(self):
        from analyzer.services.pdf_extractor import PDFExtractor
        bad = BytesIO(b'%PDF-1.4 this is not really a pdf structure')
        with self.assertRaises(ValueError):
            PDFExtractor().extract(bad)

    def test_oversized_file_rejected(self):
        from analyzer.services.pdf_extractor import PDFExtractor

        class _BigField:
            size = 999 * 1024 * 1024

            def open(self, mode='rb'):
                return self

            def read(self):
                return b'%PDF' + b'0' * 1024

            def close(self):
                pass

        with self.assertRaises(ValueError):
            PDFExtractor().extract(_BigField())


class CostEstimationTests(TestCase):
    def test_gpt4o_not_priced_as_mini(self):
        from analyzer.services.analyzer import _estimate_cost, _MODEL_PRICING
        # A versioned id that isn't an exact key exercises the partial match.
        cost = _estimate_cost('openai/gpt-4o-2024-08-06', 1_000_000, 1_000_000)
        p = _MODEL_PRICING['openai/gpt-4o']
        expected = p['input'] + p['output']  # $ for 1M input + 1M output
        self.assertAlmostEqual(float(cost), expected, places=4)
        # Sanity: this must be well above what the mini rate would produce.
        mini = _MODEL_PRICING['openai/gpt-4o-mini']
        self.assertGreater(float(cost), mini['input'] + mini['output'])
