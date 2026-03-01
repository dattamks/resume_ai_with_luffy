"""
Celery tasks for the analyzer app.

Tasks:
  - run_analysis_task: Full resume analysis pipeline (replaces threading)
  - generate_pdf_report_task: Render & upload PDF report to R2
  - cleanup_stale_analyses: Periodic — mark hung analyses as failed
  - flush_expired_tokens: Periodic — purge expired JWT blacklist entries
"""
import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db.models import Avg
from django.utils import timezone

logger = logging.getLogger('analyzer')


def _set_analysis_cache(analysis):
    """Push lightweight status into Redis for ultra-fast polling (scoped by user)."""
    data = {
        'status': analysis.status,
        'pipeline_step': analysis.pipeline_step,
        'overall_grade': analysis.overall_grade,
        'ats_score': analysis.ats_score,
        'error_message': analysis.error_message,
    }
    cache.set(
        f'analysis_status:{analysis.user_id}:{analysis.id}',
        data,
        timeout=3600,  # 1 hour TTL
    )


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=120,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_analysis_task(self, analysis_id, user_id):
    """
    Run the full resume analysis pipeline as a Celery task.

    Replaces the old `threading.Thread` approach — gives us:
    - Persistence (survives worker restarts)
    - Retry on transient failures
    - Visibility via Celery monitoring
    - Independent scaling of workers
    """
    from .models import ResumeAnalysis
    from .services.analyzer import ResumeAnalyzer

    logger.info('Task started: analysis_id=%s user_id=%s', analysis_id, user_id)

    # Track active analyses
    try:
        from resume_ai.metrics import ACTIVE_ANALYSES, ANALYSIS_TOTAL
        ACTIVE_ANALYSES.inc()
        ANALYSIS_TOTAL.labels(status='queued').inc()
    except Exception:
        pass

    import time as _time
    _task_start = _time.monotonic()

    # Release the idempotency lock as soon as the task starts — the analysis
    # record already exists so a duplicate submission would be harmless.
    cache.delete(f'analyze_lock:{user_id}')

    try:
        analysis = ResumeAnalysis.objects.get(id=analysis_id)
    except ResumeAnalysis.DoesNotExist:
        logger.error('Analysis %s not found — aborting task', analysis_id)
        return

    # Store the Celery task ID on the model
    analysis.celery_task_id = self.request.id or ''
    analysis.save(update_fields=['celery_task_id'])

    try:
        analyzer = ResumeAnalyzer()
        result = analyzer.run(analysis)
        logger.info('Analysis complete: id=%s ATS=%s', analysis_id, result.ats_score)

        # Prometheus: record success duration
        try:
            from resume_ai.metrics import ANALYSIS_DURATION, ANALYSIS_TOTAL, ACTIVE_ANALYSES
            ANALYSIS_DURATION.labels(status='done').observe(_time.monotonic() - _task_start)
            ANALYSIS_TOTAL.labels(status='done').inc()
            ACTIVE_ANALYSES.dec()
        except Exception:
            pass

        # Update Redis cache with final status
        _set_analysis_cache(result)

        # Auto-generate PDF report after successful analysis
        generate_pdf_report_task.delay(analysis_id)

        # Send analysis completion email (respects notification preferences)
        _send_analysis_complete_email(result)

    except ValueError as exc:
        logger.warning('Analysis failed (user=%s): %s', user_id, exc)
        # Prometheus: record failure
        try:
            from resume_ai.metrics import ANALYSIS_DURATION, ANALYSIS_TOTAL, ACTIVE_ANALYSES
            ANALYSIS_DURATION.labels(status='failed').observe(_time.monotonic() - _task_start)
            ANALYSIS_TOTAL.labels(status='failed').inc()
            ACTIVE_ANALYSES.dec()
        except Exception:
            pass
        try:
            analysis.refresh_from_db()
            analysis.status = ResumeAnalysis.STATUS_FAILED
            analysis.pipeline_step = ResumeAnalysis.STEP_FAILED
            analysis.error_message = str(exc)
            analysis.save(update_fields=['status', 'pipeline_step', 'error_message'])
            _set_analysis_cache(analysis)
        except Exception:
            pass
        # Refund credits on failure
        _refund_analysis_credits(analysis)

    except Exception as exc:
        logger.exception('Unexpected error during analysis (user=%s)', user_id)
        # Prometheus: record failure
        try:
            from resume_ai.metrics import ANALYSIS_DURATION, ANALYSIS_TOTAL, ACTIVE_ANALYSES
            ANALYSIS_DURATION.labels(status='failed').observe(_time.monotonic() - _task_start)
            ANALYSIS_TOTAL.labels(status='failed').inc()
            ACTIVE_ANALYSES.dec()
        except Exception:
            pass
        try:
            analysis.refresh_from_db()
            analysis.status = ResumeAnalysis.STATUS_FAILED
            analysis.pipeline_step = ResumeAnalysis.STEP_FAILED
            analysis.error_message = str(exc)
            analysis.save(update_fields=['status', 'pipeline_step', 'error_message'])
            _set_analysis_cache(analysis)
        except Exception:
            pass

        is_retriable = isinstance(exc, (ConnectionError, OSError))
        will_retry = is_retriable and self.request.retries < self.max_retries

        if will_retry:
            # Don't refund — the task will be retried and may succeed.
            # Credits stay deducted until final success or final failure.
            raise
        else:
            # Final failure — refund credits
            _refund_analysis_credits(analysis)


def _refund_analysis_credits(analysis):
    """
    Refund credits for a failed analysis.
    Only refunds if credits were actually deducted (credits_deducted=True).
    Sets credits_deducted=False after refund to prevent double-refund.
    """
    try:
        analysis.refresh_from_db()
        if not analysis.credits_deducted:
            return

        from accounts.services import refund_credits
        from django.contrib.auth.models import User

        user = User.objects.get(id=analysis.user_id)
        refund_credits(
            user,
            'resume_analysis',
            description=f'Refund: analysis #{analysis.id} failed',
            reference_id=str(analysis.id),
        )

        analysis.credits_deducted = False
        analysis.save(update_fields=['credits_deducted'])
        logger.info('Credits refunded for failed analysis id=%s', analysis.id)
    except Exception:
        logger.exception('Failed to refund credits for analysis id=%s', analysis.id)


def _send_analysis_complete_email(analysis):
    """
    Send an analysis-complete email notification.
    Respects user notification preferences (feature_updates_email).
    Falls back silently if the email template doesn't exist yet.
    """
    try:
        from django.contrib.auth.models import User
        user = User.objects.select_related('notification_preferences').get(id=analysis.user_id)

        # Respect notification preferences
        notif_prefs = getattr(user, 'notification_preferences', None)
        if notif_prefs and not notif_prefs.feature_updates_email:
            logger.debug('Analysis complete email skipped: user=%s has feature_updates_email=False', user.id)
            return

        from accounts.email_utils import send_templated_email
        send_templated_email(
            slug='analysis-complete',
            recipient=user.email,
            context={
                'username': user.first_name or user.username,
                'analysis_id': analysis.id,
                'jd_role': analysis.jd_role or 'your resume',
                'jd_company': analysis.jd_company or '',
                'overall_grade': analysis.overall_grade or '—',
                'ats_score': analysis.ats_score or '—',
                'analysis_url': f'/analyses/{analysis.id}/',
            },
            fail_silently=True,
        )
        logger.info('Analysis complete email sent: user=%s analysis=%s', user.id, analysis.id)
    except Exception:
        logger.debug('Analysis complete email not sent (template may not exist): analysis=%s', analysis.id)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_pdf_report_task(self, analysis_id):
    """
    Render a PDF report for a completed analysis and upload it to R2.

    The PDF is saved to the `report_pdf` FileField on ResumeAnalysis,
    which automatically uses R2 when configured.
    """
    from .models import ResumeAnalysis
    from .services.pdf_report import generate_analysis_pdf

    logger.info('PDF report task started: analysis_id=%s', analysis_id)

    try:
        analysis = ResumeAnalysis.objects.get(id=analysis_id)
    except ResumeAnalysis.DoesNotExist:
        logger.error('Analysis %s not found — aborting PDF task', analysis_id)
        return

    if analysis.status != ResumeAnalysis.STATUS_DONE:
        logger.warning('Analysis %s not done (status=%s) — skipping PDF', analysis_id, analysis.status)
        return

    # Skip if PDF already generated
    if analysis.report_pdf:
        logger.info('Analysis %s already has a PDF — skipping', analysis_id)
        return

    try:
        pdf_bytes = generate_analysis_pdf(analysis)

        role_slug = (analysis.jd_role or 'analysis').replace(' ', '_')[:30]
        filename = f'reports/resume_ai_{role_slug}_{analysis.pk}.pdf'

        # Save to FileField — goes to R2 when configured, local otherwise
        analysis.report_pdf.save(filename, ContentFile(pdf_bytes), save=True)
        logger.info('PDF report saved: analysis_id=%s file=%s', analysis_id, filename)

        # Update cache so frontend sees the PDF URL immediately
        _set_analysis_cache(analysis)

    except Exception as exc:
        logger.exception('PDF generation failed for analysis %s', analysis_id)
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


@shared_task(ignore_result=True)
def cleanup_stale_analyses():
    """
    Periodic task: mark analyses stuck in 'processing' for > 30 min as failed.
    This catches cases where a Celery worker died mid-pipeline.
    Also refunds credits for these stale analyses.
    """
    from django.db import transaction
    from .models import ResumeAnalysis

    cutoff = timezone.now() - timezone.timedelta(minutes=30)

    # Atomic: refund + update must happen together so the queryset doesn't
    # change between the refund loop and the bulk status update.
    with transaction.atomic():
        stale = ResumeAnalysis.objects.select_for_update().filter(
            status=ResumeAnalysis.STATUS_PROCESSING,
            updated_at__lt=cutoff,
        )

        # Refund credits for each stale analysis before bulk-updating
        for analysis in stale.filter(credits_deducted=True):
            _refund_analysis_credits(analysis)

        count = stale.update(
            status=ResumeAnalysis.STATUS_FAILED,
            pipeline_step=ResumeAnalysis.STEP_FAILED,
            error_message='Analysis timed out (worker may have crashed). Please retry.',
        )
    if count:
        logger.info('Marked %d stale analyses as failed', count)


@shared_task(ignore_result=True)
def flush_expired_tokens():
    """
    Periodic task: purge expired entries from the JWT token blacklist.
    Equivalent to `python manage.py flushexpiredtokens`.
    """
    from django.core.management import call_command

    logger.info('Flushing expired JWT tokens...')
    call_command('flushexpiredtokens')
    logger.info('Expired JWT tokens flushed')


# ── Resume generation task ───────────────────────────────────────────────

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_improved_resume_task(self, generated_resume_id):
    """
    Generate an improved resume from analysis findings.

    Pipeline:
    1. Build rewrite prompt from analysis report
    2. Call LLM to get structured resume JSON
    3. Render to PDF or DOCX
    4. Upload to R2 (or local storage)
    5. Update GeneratedResume record
    """
    from .models import GeneratedResume, LLMResponse
    from .services.resume_generator import call_llm_for_rewrite
    from .services.template_registry import get_renderer

    logger.info('Resume generation task started: id=%s', generated_resume_id)

    try:
        gen = GeneratedResume.objects.select_related('analysis', 'analysis__user').get(
            id=generated_resume_id,
        )
    except GeneratedResume.DoesNotExist:
        logger.error('GeneratedResume %s not found — aborting', generated_resume_id)
        return

    analysis = gen.analysis

    # Mark as processing
    gen.status = GeneratedResume.STATUS_PROCESSING
    gen.celery_task_id = self.request.id or ''
    gen.save(update_fields=['status', 'celery_task_id'])

    try:
        # Step 1+2: Call LLM for rewrite
        result = call_llm_for_rewrite(analysis)

        # Step 3: Save LLM response record
        llm_record = LLMResponse.objects.create(
            user=analysis.user,
            prompt_sent=result['prompt'],
            raw_response=result['raw'],
            parsed_response=result['parsed'],
            model_used=result['model'],
            status=LLMResponse.STATUS_DONE,
            duration_seconds=result['duration'],
        )

        gen.llm_response = llm_record
        gen.resume_content = result['parsed']

        # Step 4: Render to file using template registry
        renderer = get_renderer(gen.template, gen.format)
        file_bytes = renderer(result['parsed'])
        if gen.format == GeneratedResume.FORMAT_DOCX:
            ext = 'docx'
            content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        else:
            ext = 'pdf'
            content_type = 'application/pdf'

        # Build filename
        name = result['parsed'].get('contact', {}).get('name', 'resume')
        name_slug = name.replace(' ', '_')[:30]
        role_slug = (analysis.jd_role or 'general').replace(' ', '_')[:30]
        filename = f'generated_resumes/{name_slug}_{role_slug}_{gen.pk}.{ext}'

        # Step 5: Save file to storage (R2 or local)
        gen.file.save(filename, ContentFile(file_bytes), save=False)
        gen.status = GeneratedResume.STATUS_DONE
        gen.save(update_fields=[
            'llm_response', 'resume_content', 'file', 'status',
        ])

        logger.info(
            'Resume generated: id=%s analysis=%s format=%s file=%s (%.2fs LLM)',
            gen.id, analysis.id, gen.format, filename, result['duration'],
        )

    except ValueError as exc:
        logger.warning('Resume generation failed: id=%s error=%s', gen.id, exc)
        gen.status = GeneratedResume.STATUS_FAILED
        gen.error_message = str(exc)
        gen.save(update_fields=['status', 'error_message'])
        _refund_generation_credits(gen)

    except Exception as exc:
        logger.exception('Unexpected error in resume generation: id=%s', gen.id)
        gen.status = GeneratedResume.STATUS_FAILED
        gen.error_message = str(exc)
        gen.save(update_fields=['status', 'error_message'])
        _refund_generation_credits(gen)
        # Retry on transient errors
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


def _refund_generation_credits(gen):
    """
    Refund credits for a failed resume generation.
    Only refunds if credits were actually deducted.
    """
    try:
        gen.refresh_from_db()
        if not gen.credits_deducted:
            return

        from accounts.services import refund_credits
        from django.contrib.auth.models import User

        user = User.objects.get(id=gen.user_id)
        refund_credits(
            user,
            'resume_generation',
            description=f'Refund: resume generation #{gen.id} failed',
            reference_id=str(gen.id),
        )

        gen.credits_deducted = False
        gen.save(update_fields=['credits_deducted'])
        logger.info('Credits refunded for failed resume generation id=%s', gen.id)
    except Exception:
        logger.exception('Failed to refund credits for resume generation id=%s', gen.id)


# ── Resume builder (chat) rendering task ─────────────────────────────────

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def render_builder_resume_task(self, generated_resume_id):
    """
    Render a resume created via the conversational builder.

    Unlike generate_improved_resume_task, resume_content is already set
    by the builder service — this task only renders and uploads the file.
    """
    from .models import GeneratedResume
    from .services.template_registry import get_renderer

    logger.info('Builder render task started: id=%s', generated_resume_id)

    try:
        gen = GeneratedResume.objects.select_related('user').get(
            id=generated_resume_id,
        )
    except GeneratedResume.DoesNotExist:
        logger.error('GeneratedResume %s not found — aborting', generated_resume_id)
        return

    gen.status = GeneratedResume.STATUS_PROCESSING
    gen.celery_task_id = self.request.id or ''
    gen.save(update_fields=['status', 'celery_task_id'])

    try:
        renderer = get_renderer(gen.template, gen.format)
        file_bytes = renderer(gen.resume_content)

        if gen.format == GeneratedResume.FORMAT_DOCX:
            ext = 'docx'
        else:
            ext = 'pdf'

        name = gen.resume_content.get('contact', {}).get('name', 'resume')
        name_slug = name.replace(' ', '_')[:30]
        filename = f'generated_resumes/{name_slug}_builder_{gen.pk}.{ext}'

        gen.file.save(filename, ContentFile(file_bytes), save=False)
        gen.status = GeneratedResume.STATUS_DONE
        gen.save(update_fields=['file', 'status'])

        logger.info(
            'Builder resume rendered: id=%s format=%s file=%s',
            gen.id, gen.format, filename,
        )

    except Exception as exc:
        logger.exception('Builder render failed: id=%s', gen.id)
        gen.status = GeneratedResume.STATUS_FAILED
        gen.error_message = str(exc)
        gen.save(update_fields=['status', 'error_message'])

        # Refund credits
        _refund_builder_credits(gen)

        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


def _refund_builder_credits(gen):
    """Refund credits for a failed builder resume render."""
    try:
        gen.refresh_from_db()
        if not gen.credits_deducted:
            return

        from accounts.services import refund_credits
        from django.contrib.auth.models import User

        user = User.objects.get(id=gen.user_id)
        refund_credits(
            user,
            'resume_builder',
            description=f'Refund: builder resume #{gen.id} render failed',
            reference_id=str(gen.id),
        )

        gen.credits_deducted = False
        gen.save(update_fields=['credits_deducted'])
        logger.info('Credits refunded for failed builder render id=%s', gen.id)
    except Exception:
        logger.exception('Failed to refund credits for builder render id=%s', gen.id)


# ── Phase 11: Smart Job Alerts ────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def extract_job_search_profile_task(self, resume_id):
    """
    Extract a job search profile from a resume using the LLM.
    Triggered automatically when a JobAlert is created.

    Saves (or updates) the JobSearchProfile OneToOne record for the resume.
    """
    from .models import Resume, JobSearchProfile
    from .services.job_search_profile import extract_search_profile

    logger.info('Job search profile extraction started: resume_id=%s', resume_id)

    try:
        resume = Resume.objects.get(id=resume_id)
    except Resume.DoesNotExist:
        logger.error('Resume %s not found — aborting profile extraction', resume_id)
        return

    try:
        result = extract_search_profile(resume)

        # Upsert JobSearchProfile
        profile, _ = JobSearchProfile.objects.update_or_create(
            resume=resume,
            defaults={
                'titles': result['titles'],
                'skills': result['skills'],
                'seniority': result['seniority'],
                'industries': result['industries'],
                'locations': result['locations'],
                'experience_years': result['experience_years'],
                'raw_extraction': result['raw_extraction'],
            },
        )
        logger.info(
            'JobSearchProfile saved: resume=%s seniority=%s titles=%s',
            resume_id, profile.seniority, profile.titles[:2],
        )

        # Phase 12: Chain embedding computation
        compute_resume_embedding_task.delay(str(resume_id))

    except ValueError as exc:
        logger.warning('Profile extraction failed (resume=%s): %s', resume_id, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception('Unexpected error in profile extraction (resume=%s)', resume_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    acks_late=True,
)
def match_jobs_task(self, job_alert_id, discovered_job_ids):
    """
    Score a set of DiscoveredJob objects for relevance to a JobAlert.
    Creates JobMatch records for jobs scoring ≥ MATCH_THRESHOLD.
    Chains send_job_alert_notification_task on completion.
    """
    import time as _time
    from django.utils import timezone
    from .models import JobAlert, DiscoveredJob, JobMatch, JobAlertRun
    from .services.job_matcher import match_jobs, MATCH_THRESHOLD
    from accounts.services import deduct_credits, refund_credits, InsufficientCreditsError

    logger.info('match_jobs_task: alert=%s jobs=%d', job_alert_id, len(discovered_job_ids))

    try:
        alert = JobAlert.objects.select_related(
            'user', 'resume', 'resume__job_search_profile',
        ).get(id=job_alert_id)
    except JobAlert.DoesNotExist:
        logger.error('JobAlert %s not found — aborting match task', job_alert_id)
        return

    start = _time.monotonic()
    run = JobAlertRun.objects.create(job_alert=alert)

    # Only deduct credits on the first attempt (not on retries)
    credits_used = 0
    if self.request.retries == 0:
        try:
            deduct_credits(
                alert.user,
                'job_alert_run',
                description=f'Job alert run #{run.id}',
                reference_id=str(run.id),
            )
            credits_used = 1
            run.credits_deducted = True
            run.save(update_fields=['credits_deducted'])
        except InsufficientCreditsError as e:
            logger.warning('Insufficient credits for alert %s (balance=%d) — skipping run', job_alert_id, e.balance)
            run.error_message = f'Insufficient credits (balance={e.balance})'
            run.save(update_fields=['error_message'])
            return
    else:
        # On retry, check if credits were already deducted for this run
        run.refresh_from_db()
        credits_used = 1 if run.credits_deducted else 0

    try:
        discovered_jobs = DiscoveredJob.objects.filter(id__in=discovered_job_ids)
        run.jobs_discovered = discovered_jobs.count()

        scored = match_jobs(alert, discovered_jobs)

        # Build a map: DiscoveredJob.id → DiscoveredJob
        job_map = {str(j.id): j for j in discovered_jobs}

        matches_created = 0
        for item in scored:
            if item['score'] < MATCH_THRESHOLD:
                continue
            dj = job_map.get(item['discovered_job_id'])
            if not dj:
                continue
            _, created = JobMatch.objects.get_or_create(
                job_alert=alert,
                discovered_job=dj,
                defaults={
                    'relevance_score': item['score'],
                    'match_reason': item['reason'],
                },
            )
            if created:
                matches_created += 1

        duration = _time.monotonic() - start
        run.jobs_matched = matches_created
        run.credits_used = credits_used
        run.duration_seconds = round(duration, 2)
        run.save(update_fields=['jobs_discovered', 'jobs_matched', 'credits_used', 'duration_seconds'])

        logger.info(
            'match_jobs_task done: alert=%s discovered=%d matched=%d (%.2fs)',
            job_alert_id, run.jobs_discovered, matches_created, duration,
        )

        # Chain notification task
        send_job_alert_notification_task.delay(str(alert.id), str(run.id))

    except Exception as exc:
        logger.exception('match_jobs_task failed for alert %s', job_alert_id)
        duration = _time.monotonic() - start
        run.error_message = str(exc)
        run.duration_seconds = round(duration, 2)
        run.save(update_fields=['error_message', 'duration_seconds'])
        # Refund credits on failure
        if run.credits_deducted:
            try:
                refund_credits(
                    alert.user,
                    'job_alert_run',
                    description=f'Refund: job alert run #{run.id} failed',
                    reference_id=str(run.id),
                )
            except Exception:
                logger.exception('Failed to refund credits for run %s', run.id)
        raise self.retry(exc=exc)


@shared_task(ignore_result=True)
def send_job_alert_notification_task(job_alert_id, run_id):
    """
    Send an email digest if new job matches were found for a JobAlert.

    Checks:
    - matches_created > 0
    - User has job_alerts_email notification preference enabled
    - Alert is still active
    """
    from .models import JobAlert, JobAlertRun, JobMatch

    logger.info('send_job_alert_notification_task: alert=%s run=%s', job_alert_id, run_id)

    try:
        alert = JobAlert.objects.select_related('user').get(id=job_alert_id)
        run = JobAlertRun.objects.get(id=run_id)
    except (JobAlert.DoesNotExist, JobAlertRun.DoesNotExist) as exc:
        logger.error('send_job_alert_notification_task: alert or run not found: %s', exc)
        return

    if run.jobs_matched == 0:
        logger.info('No new matches for alert %s — skipping notification', job_alert_id)
        return

    # Check notification preference
    user = alert.user
    notif_prefs = getattr(user, 'notification_preferences', None)
    job_alerts_email = getattr(notif_prefs, 'job_alerts_email', True) if notif_prefs else True

    if not job_alerts_email:
        logger.info('User %s has job_alerts_email disabled — skipping notification', user.id)
        return

    # Fetch top matches (up to 10) sorted by relevance score
    top_matches = (
        JobMatch.objects
        .filter(job_alert=alert, user_feedback=JobMatch.FEEDBACK_PENDING)
        .select_related('discovered_job')
        .order_by('-relevance_score')[:10]
    )

    matches_data = [
        {
            'title': m.discovered_job.title,
            'company': m.discovered_job.company,
            'location': m.discovered_job.location,
            'url': m.discovered_job.url,
            'score': m.relevance_score,
            'reason': m.match_reason,
            'salary': m.discovered_job.salary_range,
        }
        for m in top_matches
    ]

    try:
        from accounts.email_utils import send_templated_email
        sent = send_templated_email(
            slug='job-alert-digest',
            recipient=user.email,
            context={
                'username': user.first_name or user.username,
                'alert_id': str(alert.id),
                'frequency': alert.frequency,
                'matches_count': run.jobs_matched,
                'matches': matches_data,
                'manage_url': f'/job-alerts/{alert.id}/',
            },
            fail_silently=True,
        )
        if sent:
            run.notification_sent = True
            run.save(update_fields=['notification_sent'])
            logger.info('Job alert digest sent: user=%s alert=%s matches=%d', user.id, alert.id, run.jobs_matched)
        else:
            logger.warning('Email template job-alert-digest not found or failed for user=%s', user.id)
    except Exception:
        logger.exception('Failed to send job alert notification: alert=%s', job_alert_id)


# ── Phase 12: Firecrawl + pgvector Job Alerts ─────────────────────────────────


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=60,
    acks_late=True,
)
def compute_resume_embedding_task(self, resume_id):
    """
    Compute and store the embedding for a resume on its JobSearchProfile.

    Triggered:
    - After resume upload (if JobSearchProfile exists)
    - After extract_job_search_profile_task completes
    """
    from .models import Resume, JobSearchProfile

    logger.info('Computing resume embedding: resume_id=%s', resume_id)

    try:
        resume = Resume.objects.get(id=resume_id)
    except Resume.DoesNotExist:
        logger.error('Resume %s not found — aborting embedding', resume_id)
        return

    try:
        profile = resume.job_search_profile
    except JobSearchProfile.DoesNotExist:
        logger.warning('No JobSearchProfile for resume %s — skipping embedding', resume_id)
        return

    # Check if model supports embedding field (pgvector on PostgreSQL)
    if not hasattr(profile, 'embedding'):
        logger.info('pgvector not available — skipping embedding for resume %s', resume_id)
        return

    try:
        from .services.embedding_service import compute_resume_embedding
        embedding = compute_resume_embedding(resume)
        profile.embedding = embedding
        profile.save(update_fields=['embedding'])
        logger.info('Resume embedding saved: resume=%s dims=%d', resume_id, len(embedding))
    except ValueError as exc:
        logger.warning('Resume embedding failed (resume=%s): %s', resume_id, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception('Unexpected error computing resume embedding (resume=%s)', resume_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


@shared_task(ignore_result=True)
def crawl_jobs_daily_task():
    """
    Phase 12 — Global daily job crawl task.

    Runs once daily (2 AM IST / 20:30 UTC via Celery Beat).
    1. Collect unique search queries from ALL active JobSearchProfiles
    2. Scrape job board pages via Firecrawl
    3. Extract structured listings via LLM (1 call per page)
    4. Dedup and save DiscoveredJob records
    5. Compute embeddings for new jobs
    6. Chain match_all_alerts_task

    This replaces the per-alert discover_jobs_task from Phase 11.
    """
    import time as _time
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from .models import JobAlert, DiscoveredJob, JobSearchProfile, CrawlSource
    from .services.job_sources.factory import get_job_sources
    from .services.embedding_service import compute_job_embedding

    start = _time.monotonic()
    now = timezone.now()

    # Gather unique search queries from all active alerts' profiles
    active_alerts = (
        JobAlert.objects
        .filter(is_active=True)
        .select_related('resume', 'resume__job_search_profile')
    )

    all_queries = set()
    all_locations = set()
    for alert in active_alerts:
        try:
            profile = alert.resume.job_search_profile
        except (JobSearchProfile.DoesNotExist, AttributeError):
            continue
        for title in (profile.titles or [])[:3]:
            all_queries.add(title)
        for loc in (profile.locations or [])[:2]:
            all_locations.add(loc)
        # Also add preference-based location
        pref_loc = (alert.preferences or {}).get('location', '')
        if pref_loc:
            all_locations.add(pref_loc)

    if not all_queries:
        logger.info('crawl_jobs_daily_task: no search queries found from active alerts')
        return

    queries = list(all_queries)[:20]  # Cap queries to control costs
    location = list(all_locations)[0] if all_locations else ''

    logger.info(
        'crawl_jobs_daily_task: %d unique queries, location=%r from %d active alerts',
        len(queries), location, active_alerts.count(),
    )

    # Fetch from all configured sources
    sources = get_job_sources()
    if not sources:
        logger.warning('crawl_jobs_daily_task: no job sources configured')
        return

    all_listings = []
    max_total = getattr(settings, 'MAX_CRAWL_JOBS_PER_RUN', 200)
    for source in sources:
        try:
            listings = source.search(queries=queries, location=location)
            all_listings.extend(listings)
        except Exception as exc:
            logger.warning('Source %s failed: %s', source.name(), exc)

    logger.info('crawl_jobs_daily_task: %d raw listings from crawl', len(all_listings))

    # Dedup and save DiscoveredJob records
    new_job_ids = []
    for listing in all_listings[:max_total]:
        if not listing.url and not listing.external_id:
            continue
        if not listing.external_id:
            continue

        posted_at = None
        if listing.posted_at:
            try:
                posted_at = parse_datetime(listing.posted_at)
            except Exception:
                pass

        job, created = DiscoveredJob.objects.get_or_create(
            source=listing.source,
            external_id=listing.external_id,
            defaults={
                'url': listing.url,
                'title': listing.title,
                'company': listing.company,
                'location': listing.location,
                'salary_range': listing.salary_range,
                'description_snippet': listing.description_snippet,
                'posted_at': posted_at,
                'raw_data': listing.raw_data,
                'source_page_url': getattr(listing, 'source_page_url', ''),
                'skills_required': getattr(listing, 'skills_required', []),
                'skills_nice_to_have': getattr(listing, 'skills_nice_to_have', []),
                'experience_years_min': getattr(listing, 'experience_years_min', None),
                'experience_years_max': getattr(listing, 'experience_years_max', None),
                'employment_type': getattr(listing, 'employment_type', ''),
                'remote_policy': getattr(listing, 'remote_policy', ''),
                'seniority_level': getattr(listing, 'seniority_level', ''),
                'industry': getattr(listing, 'industry', ''),
                'education_required': getattr(listing, 'education_required', ''),
                'salary_min_usd': getattr(listing, 'salary_min_usd', None),
                'salary_max_usd': getattr(listing, 'salary_max_usd', None),
            },
        )
        if created:
            new_job_ids.append(str(job.id))

    logger.info('crawl_jobs_daily_task: %d new jobs saved', len(new_job_ids))

    # Compute embeddings for new jobs (if pgvector available)
    if new_job_ids and hasattr(DiscoveredJob, 'embedding'):
        embedded_count = 0
        for job_id in new_job_ids:
            try:
                job = DiscoveredJob.objects.get(id=job_id)
                embedding = compute_job_embedding(
                    title=job.title,
                    company=job.company,
                    description=job.description_snippet,
                )
                job.embedding = embedding
                job.save(update_fields=['embedding'])
                embedded_count += 1
            except Exception as exc:
                logger.warning('Failed to embed job %s: %s', job_id, exc)
        logger.info('crawl_jobs_daily_task: %d/%d jobs embedded', embedded_count, len(new_job_ids))

    duration = _time.monotonic() - start
    logger.info('crawl_jobs_daily_task: completed in %.2fs', duration)

    # Update last_crawled_at on all active CrawlSource records
    CrawlSource.objects.filter(is_active=True).update(last_crawled_at=now)

    # Chain matching task for all alerts
    if new_job_ids:
        match_all_alerts_task.delay()


@shared_task(ignore_result=True)
def crawl_jobs_for_alert_task(alert_id):
    """
    Run Firecrawl-based job crawl for a single alert (manual run endpoint).

    1. Build queries from the alert's resume JobSearchProfile
    2. Crawl via Firecrawl sources
    3. Save & embed new DiscoveredJob records
    4. Run embedding matching + create JobMatch records
    5. Chain email notification
    """
    import time as _time
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from .models import (
        JobAlert, JobAlertRun, DiscoveredJob, JobMatch, JobSearchProfile,
        SentAlert, Notification,
    )
    from .services.job_sources.factory import get_job_sources
    from .services.embedding_service import compute_job_embedding
    from .services.embedding_matcher import match_jobs_for_alert
    from accounts.services import deduct_credits, refund_credits, InsufficientCreditsError

    logger.info('crawl_jobs_for_alert_task: alert=%s', alert_id)

    try:
        alert = JobAlert.objects.select_related(
            'user', 'resume', 'resume__job_search_profile',
        ).get(id=alert_id, is_active=True)
    except JobAlert.DoesNotExist:
        logger.warning('crawl_jobs_for_alert_task: alert %s not found or inactive', alert_id)
        return

    now = timezone.now()
    start = _time.monotonic()

    # Create a run record
    run = JobAlertRun.objects.create(job_alert=alert)

    # Deduct credits
    try:
        deduct_credits(
            alert.user,
            'job_alert_run',
            description=f'Job alert run #{run.id}',
            reference_id=str(run.id),
        )
        run.credits_deducted = True
        run.credits_used = 1
        run.save(update_fields=['credits_deducted', 'credits_used'])
    except InsufficientCreditsError as e:
        logger.warning('Insufficient credits for alert %s (balance=%d)', alert_id, e.balance)
        run.error_message = f'Insufficient credits (balance={e.balance})'
        run.save(update_fields=['error_message'])
        return

    try:
        try:
            profile = alert.resume.job_search_profile
        except (JobSearchProfile.DoesNotExist, AttributeError):
            raise ValueError('No JobSearchProfile found for this resume.')

        queries = profile.titles[:3] if profile.titles else []
        if not queries:
            raise ValueError('JobSearchProfile has no titles — cannot search.')

        preferences = alert.preferences or {}
        location = preferences.get('location', '')
        if not location and profile.locations:
            location = profile.locations[0]

        # Crawl via Firecrawl
        sources = get_job_sources()
        all_listings = []
        for source in sources:
            try:
                listings = source.search(queries=queries, location=location)
                all_listings.extend(listings)
            except Exception as exc:
                logger.warning('Source %s failed for alert %s: %s', source.name(), alert.id, exc)

        logger.info('crawl_jobs_for_alert_task: alert=%s found %d raw listings', alert_id, len(all_listings))

        # Dedup and save
        new_job_ids = []
        for listing in all_listings[:100]:
            if not listing.url or not listing.external_id:
                continue

            excluded = preferences.get('excluded_companies', [])
            if listing.company and any(
                ex.lower() in listing.company.lower() for ex in excluded
            ):
                continue

            posted_at = None
            if listing.posted_at:
                try:
                    posted_at = parse_datetime(listing.posted_at)
                except Exception:
                    pass

            job, created = DiscoveredJob.objects.get_or_create(
                source=listing.source,
                external_id=listing.external_id,
                defaults={
                    'url': listing.url,
                    'title': listing.title,
                    'company': listing.company,
                    'location': listing.location,
                    'salary_range': listing.salary_range,
                    'description_snippet': listing.description_snippet,
                    'posted_at': posted_at,
                    'raw_data': listing.raw_data,
                    'source_page_url': getattr(listing, 'source_page_url', ''),
                    'skills_required': getattr(listing, 'skills_required', []),
                    'skills_nice_to_have': getattr(listing, 'skills_nice_to_have', []),
                    'experience_years_min': getattr(listing, 'experience_years_min', None),
                    'experience_years_max': getattr(listing, 'experience_years_max', None),
                    'employment_type': getattr(listing, 'employment_type', ''),
                    'remote_policy': getattr(listing, 'remote_policy', ''),
                    'seniority_level': getattr(listing, 'seniority_level', ''),
                    'industry': getattr(listing, 'industry', ''),
                    'education_required': getattr(listing, 'education_required', ''),
                    'salary_min_usd': getattr(listing, 'salary_min_usd', None),
                    'salary_max_usd': getattr(listing, 'salary_max_usd', None),
                },
            )
            if created:
                new_job_ids.append(str(job.id))

        run.jobs_discovered = len(new_job_ids)
        run.save(update_fields=['jobs_discovered'])

        # Embed new jobs
        if new_job_ids and hasattr(DiscoveredJob, 'embedding'):
            for job_id in new_job_ids:
                try:
                    job = DiscoveredJob.objects.get(id=job_id)
                    embedding = compute_job_embedding(
                        title=job.title, company=job.company,
                        description=job.description_snippet,
                    )
                    job.embedding = embedding
                    job.save(update_fields=['embedding'])
                except Exception as exc:
                    logger.warning('Failed to embed job %s: %s', job_id, exc)

        # Run matching
        scored = match_jobs_for_alert(alert, job_ids=new_job_ids if new_job_ids else None)
        job_map = {str(j.id): j for j in DiscoveredJob.objects.filter(
            id__in=[s['discovered_job_id'] for s in scored]
        )}

        matches_created = 0
        for item in scored:
            dj = job_map.get(item['discovered_job_id'])
            if not dj:
                continue
            _, created = JobMatch.objects.get_or_create(
                job_alert=alert,
                discovered_job=dj,
                defaults={
                    'relevance_score': item['score'],
                    'match_reason': item['reason'],
                },
            )
            if created:
                matches_created += 1
                # In-app notification with dedup
                _, sent_created = SentAlert.objects.get_or_create(
                    user=alert.user, discovered_job=dj,
                    channel=SentAlert.CHANNEL_IN_APP,
                )
                if sent_created:
                    Notification.objects.create(
                        user=alert.user,
                        title=f'New job match: {dj.title[:80]}',
                        body=f'{dj.company} — {dj.location}' if dj.company else dj.title,
                        link=dj.url or f'/job-alerts/{alert.id}/matches/',
                        notification_type=Notification.TYPE_JOB_MATCH,
                        metadata={
                            'job_id': str(dj.id),
                            'alert_id': str(alert.id),
                            'company': dj.company,
                        },
                    )

        duration = _time.monotonic() - start
        run.jobs_matched = matches_created
        run.duration_seconds = round(duration, 2)
        run.save(update_fields=['jobs_matched', 'duration_seconds'])

        alert.last_run_at = now
        alert.set_next_run()
        alert.save(update_fields=['last_run_at', 'next_run_at'])

        logger.info(
            'crawl_jobs_for_alert_task done: alert=%s discovered=%d matched=%d (%.2fs)',
            alert_id, len(new_job_ids), matches_created, duration,
        )

        if matches_created > 0:
            send_job_alert_notification_task.delay(str(alert.id), str(run.id))

    except Exception as exc:
        logger.exception('crawl_jobs_for_alert_task failed for alert %s', alert_id)
        duration = _time.monotonic() - start
        run.error_message = str(exc)
        run.duration_seconds = round(duration, 2)
        run.save(update_fields=['error_message', 'duration_seconds'])
        # Refund credits on failure
        if run.credits_deducted:
            try:
                refund_credits(
                    alert.user, 'job_alert_run',
                    description=f'Refund: manual alert run #{run.id} failed',
                    reference_id=str(run.id),
                )
            except Exception:
                logger.exception('Failed to refund credits for run %s', run.id)


@shared_task(ignore_result=True)
def match_all_alerts_task():
    """
    Phase 12 — Match all active alerts against recently discovered jobs.

    For each active JobAlert:
    1. Run pgvector cosine similarity (or LLM fallback)
    2. Create JobMatch records for matches above threshold
    3. Create in-app Notification + SentAlert dedup records
    4. Send email digest if user has notifications enabled

    This replaces per-alert match_jobs_task chaining from Phase 11.
    """
    import time as _time
    from django.utils import timezone
    from .models import (
        JobAlert, DiscoveredJob, JobMatch, JobAlertRun,
        SentAlert, Notification,
    )
    from .services.embedding_matcher import match_jobs_for_alert

    start = _time.monotonic()
    now = timezone.now()

    active_alerts = (
        JobAlert.objects
        .filter(is_active=True)
        .select_related('user', 'resume', 'resume__job_search_profile')
    )

    total_matched = 0

    for alert in active_alerts:
        try:
            run = JobAlertRun.objects.create(job_alert=alert)

            # Use embedding matching
            scored = match_jobs_for_alert(alert)

            # Build JobMatch records
            job_map = {}
            if scored:
                dj_ids = [s['discovered_job_id'] for s in scored]
                job_map = {
                    str(j.id): j
                    for j in DiscoveredJob.objects.filter(id__in=dj_ids)
                }

            matches_created = 0
            new_match_jobs = []
            for item in scored:
                dj = job_map.get(item['discovered_job_id'])
                if not dj:
                    continue

                _, created = JobMatch.objects.get_or_create(
                    job_alert=alert,
                    discovered_job=dj,
                    defaults={
                        'relevance_score': item['score'],
                        'match_reason': item['reason'],
                    },
                )
                if created:
                    matches_created += 1
                    new_match_jobs.append(dj)

            # Create in-app notifications + dedup records for new matches
            for dj in new_match_jobs:
                # Dedup check — skip if already notified
                _, sent_created = SentAlert.objects.get_or_create(
                    user=alert.user,
                    discovered_job=dj,
                    channel=SentAlert.CHANNEL_IN_APP,
                )
                if sent_created:
                    Notification.objects.create(
                        user=alert.user,
                        title=f'New job match: {dj.title[:80]}',
                        body=f'{dj.company} — {dj.location}' if dj.company else dj.title,
                        link=dj.url or f'/job-alerts/{alert.id}/matches/',
                        notification_type=Notification.TYPE_JOB_MATCH,
                        metadata={
                            'job_id': str(dj.id),
                            'alert_id': str(alert.id),
                            'company': dj.company,
                        },
                    )

            # Update run stats
            duration = _time.monotonic() - start
            run.jobs_matched = matches_created
            run.duration_seconds = round(duration, 2)
            run.save(update_fields=['jobs_matched', 'duration_seconds'])

            # Update alert timestamps
            alert.last_run_at = now
            alert.set_next_run()
            alert.save(update_fields=['last_run_at', 'next_run_at'])

            total_matched += matches_created

            # Chain email notification if new matches found
            if matches_created > 0:
                send_job_alert_notification_task.delay(str(alert.id), str(run.id))

            logger.info(
                'match_all_alerts_task: alert=%s matched=%d',
                alert.id, matches_created,
            )

        except Exception as exc:
            logger.exception('match_all_alerts_task failed for alert %s: %s', alert.id, exc)
            continue

    duration = _time.monotonic() - start
    logger.info(
        'match_all_alerts_task: completed in %.2fs, total_matched=%d across %d alerts',
        duration, total_matched, active_alerts.count(),
    )


# ── Weekly Email Digest ──────────────────────────────────────────────────────


@shared_task(ignore_result=True)
def send_weekly_digest_task():
    """
    Periodic task (Celery Beat, weekly): send a summary email to all users with
    activity in the past week. Includes ATS score trends, analysis count, and tips.
    Respects user notification preferences (newsletters_email).
    """
    from django.contrib.auth.models import User
    from .models import ResumeAnalysis

    one_week_ago = timezone.now() - timezone.timedelta(days=7)

    # Find users with at least one completed analysis in the past week
    active_user_ids = (
        ResumeAnalysis.objects
        .filter(
            status=ResumeAnalysis.STATUS_DONE,
            created_at__gte=one_week_ago,
        )
        .values_list('user_id', flat=True)
        .distinct()
    )

    sent_count = 0
    for user_id in active_user_ids:
        try:
            user = User.objects.select_related('notification_preferences').get(id=user_id)

            # Respect notification preferences
            notif_prefs = getattr(user, 'notification_preferences', None)
            if notif_prefs and not notif_prefs.newsletters_email:
                continue

            # Gather stats
            week_analyses = ResumeAnalysis.objects.filter(
                user=user, created_at__gte=one_week_ago,
                status=ResumeAnalysis.STATUS_DONE,
            )
            count = week_analyses.count()
            avg_ats = week_analyses.aggregate(avg=Avg('ats_score'))['avg']
            best = week_analyses.order_by('-ats_score').values('jd_role', 'ats_score').first()

            from accounts.email_utils import send_templated_email
            send_templated_email(
                slug='weekly-digest',
                recipient=user.email,
                context={
                    'username': user.first_name or user.username,
                    'analyses_count': count,
                    'average_ats': round(avg_ats, 1) if avg_ats is not None else '—',
                    'best_role': best['jd_role'] if best else '—',
                    'best_score': best['ats_score'] if best else '—',
                    'dashboard_url': '/dashboard/',
                },
                fail_silently=True,
            )
            sent_count += 1
        except Exception:
            logger.debug('Weekly digest skipped for user_id=%s', user_id)

    logger.info('Weekly digest sent to %d users', sent_count)


# ── Interview Prep Generation ────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_interview_prep_task(self, prep_id, user_id):
    """
    Generate AI-powered interview preparation questions from analysis findings.

    Pipeline:
    1. Build prompt from the linked ResumeAnalysis data
    2. Call LLM for structured interview questions + tips
    3. Save parsed output to InterviewPrep record
    """
    from .models import InterviewPrep, LLMResponse
    from .services.interview_prep import build_interview_prep_prompt, call_llm_for_interview_prep

    logger.info('Interview prep task started: prep_id=%s user_id=%s', prep_id, user_id)

    try:
        prep = InterviewPrep.objects.select_related('analysis').get(id=prep_id)
    except InterviewPrep.DoesNotExist:
        logger.error('InterviewPrep %s not found — aborting', prep_id)
        return

    # Mark as processing
    prep.status = InterviewPrep.STATUS_PROCESSING
    prep.celery_task_id = self.request.id or ''
    prep.save(update_fields=['status', 'celery_task_id'])

    try:
        # Step 1: Build prompt
        prompt = build_interview_prep_prompt(prep.analysis)

        # Step 2: Call LLM
        result = call_llm_for_interview_prep(prompt)

        # Step 3: Save LLM response record
        usage = result.get('usage', {})
        llm_record = LLMResponse.objects.create(
            user_id=user_id,
            prompt_sent=result['prompt'],
            raw_response=result['raw'],
            parsed_response=result['parsed'],
            model_used=result['model'],
            status=LLMResponse.STATUS_DONE,
            duration_seconds=result['duration'],
            call_purpose='interview_prep',
            prompt_tokens=usage.get('prompt_tokens'),
            completion_tokens=usage.get('completion_tokens'),
            total_tokens=usage.get('total_tokens'),
        )

        # Step 4: Save results to InterviewPrep
        parsed = result['parsed']
        prep.llm_response = llm_record
        prep.questions = parsed.get('questions', [])
        prep.tips = parsed.get('tips', [])
        prep.status = InterviewPrep.STATUS_DONE
        prep.save(update_fields=[
            'llm_response', 'questions', 'tips', 'status',
        ])

        logger.info(
            'Interview prep generated: id=%s analysis=%s questions=%d (%.2fs LLM)',
            prep.id, prep.analysis_id, len(prep.questions or []), result['duration'],
        )

    except ValueError as exc:
        logger.warning('Interview prep failed: id=%s error=%s', prep.id, exc)
        prep.status = InterviewPrep.STATUS_FAILED
        prep.error_message = str(exc)
        prep.save(update_fields=['status', 'error_message'])
        _refund_interview_prep_credits(prep)

    except Exception as exc:
        logger.exception('Unexpected error in interview prep: id=%s', prep.id)
        prep.status = InterviewPrep.STATUS_FAILED
        prep.error_message = str(exc)
        prep.save(update_fields=['status', 'error_message'])
        _refund_interview_prep_credits(prep)
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


def _refund_interview_prep_credits(prep):
    """Refund credits for a failed interview prep generation."""
    try:
        prep.refresh_from_db()
        if not prep.credits_deducted:
            return

        from accounts.services import refund_credits
        from django.contrib.auth.models import User

        user = User.objects.get(id=prep.user_id)
        refund_credits(
            user,
            'interview_prep',
            description=f'Refund: interview prep #{prep.id} failed',
            reference_id=str(prep.id),
        )

        prep.credits_deducted = False
        prep.save(update_fields=['credits_deducted'])
        logger.info('Credits refunded for failed interview prep id=%s', prep.id)
    except Exception:
        logger.exception('Failed to refund credits for interview prep id=%s', prep.id)


# ── Cover Letter Generation ─────────────────────────────────────────────────


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    acks_late=True,
)
def generate_cover_letter_task(self, cover_letter_id, user_id):
    """
    Generate an AI-powered cover letter from analysis findings.

    Pipeline:
    1. Build prompt from the linked ResumeAnalysis data + tone preference
    2. Call LLM for structured cover letter content
    3. Save parsed output to CoverLetter record
    """
    from .models import CoverLetter, LLMResponse
    from .services.cover_letter import build_cover_letter_prompt, call_llm_for_cover_letter

    logger.info('Cover letter task started: cover_letter_id=%s user_id=%s', cover_letter_id, user_id)

    try:
        cl = CoverLetter.objects.select_related('analysis').get(id=cover_letter_id)
    except CoverLetter.DoesNotExist:
        logger.error('CoverLetter %s not found — aborting', cover_letter_id)
        return

    # Mark as processing
    cl.status = CoverLetter.STATUS_PROCESSING
    cl.celery_task_id = self.request.id or ''
    cl.save(update_fields=['status', 'celery_task_id'])

    try:
        # Step 1: Build prompt
        prompt = build_cover_letter_prompt(cl.analysis, tone=cl.tone)

        # Step 2: Call LLM
        result = call_llm_for_cover_letter(prompt)

        # Step 3: Save LLM response record
        usage = result.get('usage', {})
        llm_record = LLMResponse.objects.create(
            user_id=user_id,
            prompt_sent=result['prompt'],
            raw_response=result['raw'],
            parsed_response=result['parsed'],
            model_used=result['model'],
            status=LLMResponse.STATUS_DONE,
            duration_seconds=result['duration'],
            call_purpose='cover_letter',
            prompt_tokens=usage.get('prompt_tokens'),
            completion_tokens=usage.get('completion_tokens'),
            total_tokens=usage.get('total_tokens'),
        )

        # Step 4: Save results to CoverLetter
        parsed = result['parsed']
        cl.llm_response = llm_record
        cl.content = parsed.get('full_text', '')
        cl.content_html = parsed.get('full_html', '')
        cl.status = CoverLetter.STATUS_DONE
        cl.save(update_fields=[
            'llm_response', 'content', 'content_html', 'status',
        ])

        logger.info(
            'Cover letter generated: id=%s analysis=%s tone=%s (%.2fs LLM)',
            cl.id, cl.analysis_id, cl.tone, result['duration'],
        )

    except ValueError as exc:
        logger.warning('Cover letter failed: id=%s error=%s', cl.id, exc)
        cl.status = CoverLetter.STATUS_FAILED
        cl.error_message = str(exc)
        cl.save(update_fields=['status', 'error_message'])
        _refund_cover_letter_credits(cl)

    except Exception as exc:
        logger.exception('Unexpected error in cover letter: id=%s', cl.id)
        cl.status = CoverLetter.STATUS_FAILED
        cl.error_message = str(exc)
        cl.save(update_fields=['status', 'error_message'])
        _refund_cover_letter_credits(cl)
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


def _refund_cover_letter_credits(cl):
    """Refund credits for a failed cover letter generation."""
    try:
        cl.refresh_from_db()
        if not cl.credits_deducted:
            return

        from accounts.services import refund_credits
        from django.contrib.auth.models import User

        user = User.objects.get(id=cl.user_id)
        refund_credits(
            user,
            'cover_letter',
            description=f'Refund: cover letter #{cl.id} failed',
            reference_id=str(cl.id),
        )

        cl.credits_deducted = False
        cl.save(update_fields=['credits_deducted'])
        logger.info('Credits refunded for failed cover letter id=%s', cl.id)
    except Exception:
        logger.exception('Failed to refund credits for cover letter id=%s', cl.id)
