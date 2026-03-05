"""
Tests for the Skill Enrichment Pipeline.

Covers:
  - upsert_skills_for_job: new skill creation, counter increments, alias
    normalisation, salary tracking, role tracking
  - upsert_skills_for_jobs: batch processing
  - enrich_new_skills_task: LLM description generation (mocked)
  - _enrich_skills_from_jobs: integration helper that chains upsert + task
  - Pipeline hooks: process_ingested_jobs_task, crawl_jobs_daily_task,
    sync_analyzed_job_task all invoke skill enrichment
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from analyzer.models import DiscoveredJob, Skill


def _make_job(**kwargs):
    """Create a DiscoveredJob with sensible defaults."""
    defaults = {
        'source': 'firecrawl',
        'external_id': str(uuid.uuid4()),
        'url': 'https://example.com/job/1',
        'title': 'Backend Engineer',
        'company': 'TestCo',
        'skills_required': ['Python', 'Django'],
        'skills_nice_to_have': [],
    }
    defaults.update(kwargs)
    return DiscoveredJob.objects.create(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
#  upsert_skills_for_job
# ═══════════════════════════════════════════════════════════════════════════


class UpsertSkillsForJobTests(TestCase):
    """Test the core skill upsert function."""

    def test_creates_new_skills(self):
        """New skills are created when the job has skills not yet in the DB."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['Python', 'Django'], skills_nice_to_have=['Redis'])
        new_names, existing_names = upsert_skills_for_job(job)

        self.assertEqual(set(new_names), {'python', 'django', 'redis'})
        self.assertEqual(existing_names, [])
        self.assertEqual(Skill.objects.count(), 3)

    def test_increments_existing_counters(self):
        """Existing skill counters are incremented when job references them."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        Skill.objects.create(name='python', display_name='Python', job_count_30d=5, job_count_1y=10, job_count_5y=20)
        job = _make_job(skills_required=['Python'])

        new_names, existing_names = upsert_skills_for_job(job)

        self.assertEqual(new_names, [])
        self.assertEqual(existing_names, ['python'])

        skill = Skill.objects.get(name='python')
        self.assertEqual(skill.job_count_30d, 6)
        self.assertEqual(skill.job_count_1y, 11)
        self.assertEqual(skill.job_count_5y, 21)

    def test_mixed_new_and_existing(self):
        """Some skills exist, some don't — both paths exercised."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        Skill.objects.create(name='python', display_name='Python', job_count_30d=3)
        job = _make_job(skills_required=['Python', 'Go'], skills_nice_to_have=['Terraform'])

        new_names, existing_names = upsert_skills_for_job(job)

        self.assertEqual(set(new_names), {'go', 'terraform'})
        self.assertEqual(existing_names, ['python'])
        self.assertEqual(Skill.objects.count(), 3)

    def test_empty_skills_noop(self):
        """Job with no skills returns empty lists."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=[], skills_nice_to_have=[])
        new_names, existing_names = upsert_skills_for_job(job)

        self.assertEqual(new_names, [])
        self.assertEqual(existing_names, [])
        self.assertEqual(Skill.objects.count(), 0)

    def test_alias_normalisation(self):
        """Skills are normalised via alias lookup."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        Skill.objects.create(name='kubernetes', display_name='Kubernetes', aliases=['k8s', 'kube'])
        job = _make_job(skills_required=['k8s'])

        new_names, existing_names = upsert_skills_for_job(job)

        self.assertEqual(new_names, [])
        self.assertEqual(existing_names, ['kubernetes'])
        # Counter should be incremented on the canonical skill
        skill = Skill.objects.get(name='kubernetes')
        self.assertEqual(skill.job_count_30d, 1)

    def test_case_insensitive(self):
        """Skill names are lowercased before lookup/creation."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['PYTHON', 'Django', 'rEdIs'])
        upsert_skills_for_job(job)

        names = set(Skill.objects.values_list('name', flat=True))
        self.assertEqual(names, {'python', 'django', 'redis'})

    def test_dedup_within_job(self):
        """Duplicate skills within the same job are collapsed."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['Python', 'python'], skills_nice_to_have=['PYTHON'])
        new_names, _ = upsert_skills_for_job(job)

        self.assertEqual(len(new_names), 1)
        self.assertEqual(Skill.objects.count(), 1)

    def test_salary_tracked_for_new_skill(self):
        """New skill picks up avg salary from the job."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(
            skills_required=['Go'],
            salary_min_usd=100000,
            salary_max_usd=150000,
        )
        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='go')
        self.assertEqual(skill.avg_salary_usd, Decimal('125000.00'))

    def test_role_added_for_new_skill(self):
        """New skill records the job title in its roles list."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(title='Data Scientist', skills_required=['Pandas'])
        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='pandas')
        self.assertIn('data scientist', skill.roles)

    def test_role_added_to_existing_skill(self):
        """Existing skill gets job title appended to roles."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        Skill.objects.create(name='python', display_name='Python', roles=['backend engineer'])
        job = _make_job(title='ML Engineer', skills_required=['Python'])
        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='python')
        self.assertIn('backend engineer', skill.roles)
        self.assertIn('ml engineer', skill.roles)

    def test_role_not_duplicated(self):
        """Same role is not added twice."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        Skill.objects.create(name='python', display_name='Python', roles=['backend engineer'])
        job = _make_job(title='Backend Engineer', skills_required=['Python'])
        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='python')
        self.assertEqual(skill.roles.count('backend engineer'), 1)

    def test_display_name_auto_generated(self):
        """New skills get display_name from name.title()."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['machine_learning'])
        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='machine_learning')
        self.assertEqual(skill.display_name, 'Machine Learning')

    def test_old_job_only_increments_5y_counter(self):
        """A job older than 1y but within 5y only increments job_count_5y."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['Fortran'])
        # Backdate the job to 2 years ago
        two_years_ago = timezone.now() - timedelta(days=730)
        DiscoveredJob.objects.filter(id=job.id).update(created_at=two_years_ago)
        job.refresh_from_db()

        upsert_skills_for_job(job)

        skill = Skill.objects.get(name='fortran')
        self.assertEqual(skill.job_count_30d, 0)
        self.assertEqual(skill.job_count_1y, 0)
        self.assertEqual(skill.job_count_5y, 1)

    def test_whitespace_stripped(self):
        """Whitespace-only or padded skill names are cleaned."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['  Python  ', '', '  '])
        new_names, _ = upsert_skills_for_job(job)

        self.assertEqual(set(new_names), {'python'})
        self.assertEqual(Skill.objects.count(), 1)

    def test_non_string_skills_ignored(self):
        """Non-string entries in skills list are gracefully skipped."""
        from analyzer.services.skill_enrichment import upsert_skills_for_job

        job = _make_job(skills_required=['Python', 42, None, True])
        new_names, _ = upsert_skills_for_job(job)

        self.assertEqual(set(new_names), {'python'})


# ═══════════════════════════════════════════════════════════════════════════
#  upsert_skills_for_jobs (batch)
# ═══════════════════════════════════════════════════════════════════════════


class UpsertSkillsForJobsBatchTests(TestCase):
    """Test batch processing across multiple jobs."""

    def test_batch_collects_all_new_skills(self):
        """Processing multiple jobs returns the union of new skill names."""
        from analyzer.services.skill_enrichment import upsert_skills_for_jobs

        job1 = _make_job(skills_required=['Python', 'Go'])
        job2 = _make_job(skills_required=['Go', 'Rust'])

        new_names = upsert_skills_for_jobs([job1, job2])

        self.assertEqual(set(new_names), {'python', 'go', 'rust'})
        self.assertEqual(Skill.objects.count(), 3)

    def test_second_job_increments_first_jobs_skills(self):
        """Second job in batch increments counters for skills created by first job."""
        from analyzer.services.skill_enrichment import upsert_skills_for_jobs

        job1 = _make_job(skills_required=['Python'])
        job2 = _make_job(skills_required=['Python'])

        upsert_skills_for_jobs([job1, job2])

        skill = Skill.objects.get(name='python')
        # First job creates with count 1, second job increments to 2
        self.assertEqual(skill.job_count_30d, 2)

    def test_empty_job_list(self):
        """Empty list returns no new skills."""
        from analyzer.services.skill_enrichment import upsert_skills_for_jobs

        new_names = upsert_skills_for_jobs([])
        self.assertEqual(new_names, [])


# ═══════════════════════════════════════════════════════════════════════════
#  enrich_new_skills_task (Celery task with mocked LLM)
# ═══════════════════════════════════════════════════════════════════════════


class EnrichNewSkillsTaskTests(TestCase):
    """Test the Celery task that generates LLM descriptions."""

    def test_populates_description_and_category(self):
        """Task fills description, display_name, category, roles from LLM result."""
        Skill.objects.create(name='python', display_name='Python')
        Skill.objects.create(name='django', display_name='Django')

        mock_llm_result = [
            {
                'name': 'python',
                'display_name': 'Python',
                'description': 'A versatile programming language.',
                'category': 'language',
                'roles': ['backend engineer', 'data scientist'],
            },
            {
                'name': 'django',
                'display_name': 'Django',
                'description': 'A Python web framework.',
                'category': 'framework',
                'roles': ['backend engineer', 'full-stack developer'],
            },
        ]

        with patch(
            'analyzer.management.commands.aggregate_skills._generate_descriptions_batch',
            return_value=mock_llm_result,
        ):
            from analyzer.tasks import enrich_new_skills_task
            enrich_new_skills_task(['python', 'django'])

        python_skill = Skill.objects.get(name='python')
        self.assertEqual(python_skill.description, 'A versatile programming language.')
        self.assertEqual(python_skill.category, 'language')
        self.assertIn('backend engineer', python_skill.roles)

        django_skill = Skill.objects.get(name='django')
        self.assertEqual(django_skill.description, 'A Python web framework.')
        self.assertEqual(django_skill.category, 'framework')

    def test_skips_skills_with_existing_description(self):
        """Skills that already have a description are not overwritten."""
        Skill.objects.create(
            name='python', display_name='Python',
            description='Already has a description.',
        )

        from analyzer.tasks import enrich_new_skills_task

        with patch(
            'analyzer.management.commands.aggregate_skills._generate_descriptions_batch',
        ) as mock_batch:
            enrich_new_skills_task(['python'])
            mock_batch.assert_not_called()

    def test_empty_skill_list_noop(self):
        """Empty list exits early without LLM call."""
        from analyzer.tasks import enrich_new_skills_task

        with patch(
            'analyzer.management.commands.aggregate_skills._generate_descriptions_batch',
        ) as mock_batch:
            enrich_new_skills_task([])
            mock_batch.assert_not_called()

    def test_invalid_category_ignored(self):
        """LLM returning invalid category doesn't update the field."""
        Skill.objects.create(name='python', display_name='Python')

        mock_llm_result = [
            {
                'name': 'python',
                'display_name': 'PY',
                'description': 'A language.',
                'category': 'invalid_category',
                'roles': [],
            },
        ]

        with patch(
            'analyzer.management.commands.aggregate_skills._generate_descriptions_batch',
            return_value=mock_llm_result,
        ):
            from analyzer.tasks import enrich_new_skills_task
            enrich_new_skills_task(['python'])

        python_skill = Skill.objects.get(name='python')
        self.assertEqual(python_skill.description, 'A language.')
        self.assertEqual(python_skill.category, 'other')  # default, not updated

    def test_malformed_llm_items_skipped(self):
        """Items without 'name' key or non-dict items are skipped."""
        Skill.objects.create(name='python', display_name='Python')

        mock_llm_result = [
            'not a dict',
            {'no_name_key': True},
            {
                'name': 'python',
                'description': 'Works fine.',
                'category': 'language',
            },
        ]

        with patch(
            'analyzer.management.commands.aggregate_skills._generate_descriptions_batch',
            return_value=mock_llm_result,
        ):
            from analyzer.tasks import enrich_new_skills_task
            enrich_new_skills_task(['python'])

        python_skill = Skill.objects.get(name='python')
        self.assertEqual(python_skill.description, 'Works fine.')


# ═══════════════════════════════════════════════════════════════════════════
#  _enrich_skills_from_jobs helper
# ═══════════════════════════════════════════════════════════════════════════


class EnrichSkillsFromJobsTests(TestCase):
    """Test the helper that chains upsert + Celery task."""

    @patch('analyzer.tasks.enrich_new_skills_task')
    def test_dispatches_task_for_new_skills(self, mock_task):
        """When new skills are found, the LLM enrichment task is dispatched."""
        mock_task.delay.return_value = MagicMock()

        from analyzer.tasks import _enrich_skills_from_jobs

        job = _make_job(skills_required=['Python', 'Go'])
        new_names = _enrich_skills_from_jobs([job])

        self.assertEqual(set(new_names), {'python', 'go'})
        mock_task.delay.assert_called_once()
        # Verify skill names were passed through
        call_args = mock_task.delay.call_args[0][0]
        self.assertEqual(set(call_args), {'python', 'go'})

    @patch('analyzer.tasks.enrich_new_skills_task')
    def test_no_task_when_all_skills_exist(self, mock_task):
        """No task dispatched when all skills already exist."""
        Skill.objects.create(name='python', display_name='Python')

        from analyzer.tasks import _enrich_skills_from_jobs

        job = _make_job(skills_required=['Python'])
        new_names = _enrich_skills_from_jobs([job])

        self.assertEqual(new_names, [])
        mock_task.delay.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
#  Pipeline integration — verify hooks fire in pipeline tasks
# ═══════════════════════════════════════════════════════════════════════════


class PipelineHookTests(TestCase):
    """Verify skill enrichment is called from the ingestion pipeline tasks."""

    @patch('analyzer.tasks.cache')
    @patch('analyzer.tasks._enrich_skills_from_jobs')
    @patch('analyzer.tasks.match_all_alerts_task')
    def test_process_ingested_jobs_calls_enrichment(self, mock_match, mock_enrich, mock_cache):
        """process_ingested_jobs_task calls _enrich_skills_from_jobs."""
        mock_match.delay.return_value = MagicMock()
        mock_enrich.return_value = []
        mock_cache.add.return_value = True

        job = _make_job(skills_required=['Python'])

        from analyzer.tasks import process_ingested_jobs_task
        # .apply() runs the bound Celery task synchronously
        process_ingested_jobs_task.apply(args=([str(job.id)],))

        mock_enrich.assert_called_once()
        # Check the job was passed
        enriched_jobs = mock_enrich.call_args[0][0]
        self.assertEqual(len(enriched_jobs), 1)

    @patch('analyzer.tasks._enrich_skills_from_jobs')
    @patch('analyzer.tasks.match_all_alerts_task')
    @patch('analyzer.services.job_sources.factory.get_job_sources')
    def test_crawl_jobs_daily_calls_enrichment(self, mock_sources, mock_match, mock_enrich):
        """crawl_jobs_daily_task calls _enrich_skills_from_jobs for new jobs."""
        from analyzer.services.job_sources.base import RawJobListing
        from analyzer.models import JobAlert, JobSearchProfile, Resume
        from django.contrib.auth.models import User

        mock_enrich.return_value = []
        mock_match.delay.return_value = MagicMock()

        mock_source = MagicMock()
        mock_source.name.return_value = 'MockSource'
        mock_source.search.return_value = [
            RawJobListing(
                source='firecrawl',
                external_id='crawl-test-1',
                url='https://example.com/job/crawl-1',
                title='Data Engineer',
                company='DataCo',
                skills_required=['Spark', 'Python'],
            ),
        ]
        mock_sources.return_value = [mock_source]

        # Need at least 1 active alert with a profile for crawler to get queries
        user = User.objects.create_user(username='crawluser', password='Pass123!')
        resume = Resume.objects.create(
            user=user, original_filename='r.pdf', file_hash='h1', file_size_bytes=100,
        )
        alert = JobAlert.objects.create(user=user, resume=resume, is_active=True)
        JobSearchProfile.objects.create(
            resume=resume, titles=['Data Engineer'], skills=['Spark'],
        )

        from analyzer.tasks import crawl_jobs_daily_task
        crawl_jobs_daily_task()

        mock_enrich.assert_called_once()

    @patch('analyzer.tasks._enrich_skills_from_jobs')
    def test_sync_analyzed_job_calls_enrichment(self, mock_enrich):
        """sync_analyzed_job_task calls _enrich_skills_from_jobs."""
        from django.contrib.auth.models import User
        from analyzer.models import Resume, ResumeAnalysis

        mock_enrich.return_value = []

        user = User.objects.create_user(username='syncuser', password='Pass123!')
        resume = Resume.objects.create(
            user=user, original_filename='r.pdf', file_hash='h2', file_size_bytes=100,
        )
        analysis = ResumeAnalysis.objects.create(
            user=user, resume=resume,
            status=ResumeAnalysis.STATUS_DONE,
            jd_role='ML Engineer',
            jd_company='AICo',
            jd_skills='Python, TensorFlow, PyTorch',
            jd_url='https://example.com/job/ml',
        )

        from analyzer.tasks import sync_analyzed_job_task
        sync_analyzed_job_task(analysis.id)

        mock_enrich.assert_called_once()
        enriched_jobs = mock_enrich.call_args[0][0]
        self.assertEqual(len(enriched_jobs), 1)
