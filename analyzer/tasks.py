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
from django.core.cache import cache
from django.core.files.base import ContentFile
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

        # Update Redis cache with final status
        _set_analysis_cache(result)

        # Auto-generate PDF report after successful analysis
        generate_pdf_report_task.delay(analysis_id)

    except ValueError as exc:
        logger.warning('Analysis failed (user=%s): %s', user_id, exc)
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
        # Re-raise for Celery retry (ConnectionError etc.)
        if isinstance(exc, (ConnectionError, OSError)):
            raise


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
    from .models import ResumeAnalysis

    cutoff = timezone.now() - timezone.timedelta(minutes=30)
    stale = ResumeAnalysis.objects.filter(
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
    from .services.resume_pdf_renderer import render_resume_pdf
    from .services.resume_docx_renderer import render_resume_docx

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

        # Step 4: Render to file
        if gen.format == GeneratedResume.FORMAT_DOCX:
            file_bytes = render_resume_docx(result['parsed'])
            ext = 'docx'
            content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        else:
            file_bytes = render_resume_pdf(result['parsed'])
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

    except ValueError as exc:
        logger.warning('Profile extraction failed (resume=%s): %s', resume_id, exc)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception('Unexpected error in profile extraction (resume=%s)', resume_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


@shared_task(ignore_result=True)
def discover_jobs_task():
    """
    Periodic task (every 6 hours via Celery Beat).

    For each active JobAlert where next_run_at ≤ now:
    1. Build search queries from the resume's JobSearchProfile
    2. Call all configured job source APIs
    3. Dedup and save new DiscoveredJob records
    4. Chain match_jobs_task for each alert
    """
    from django.utils import timezone
    from .models import JobAlert, DiscoveredJob
    from .services.job_sources.factory import get_job_sources

    now = timezone.now()
    due_alerts = JobAlert.objects.filter(
        is_active=True,
        next_run_at__lte=now,
    ).select_related('resume', 'resume__job_search_profile')

    logger.info('discover_jobs_task: found %d due alerts', due_alerts.count())

    for alert in due_alerts:
        try:
            resume = alert.resume
            try:
                profile = resume.job_search_profile
            except Exception:
                logger.warning('Alert %s has no JobSearchProfile — skipping', alert.id)
                # Still update next_run_at to avoid re-running immediately
                alert.set_next_run()
                alert.save(update_fields=['next_run_at'])
                continue

            # Build search queries from profile titles
            queries = profile.titles[:3] if profile.titles else []
            if not queries:
                logger.warning('Alert %s profile has no titles — skipping', alert.id)
                alert.set_next_run()
                alert.save(update_fields=['next_run_at'])
                continue

            preferences = alert.preferences or {}
            location = preferences.get('location', '')
            if not location and profile.locations:
                location = profile.locations[0]

            # Fetch from all configured sources
            sources = get_job_sources()
            all_listings = []
            for source in sources:
                try:
                    listings = source.search(queries=queries, location=location)
                    all_listings.extend(listings)
                except Exception as exc:
                    logger.warning('Source %s failed for alert %s: %s', source.name(), alert.id, exc)

            logger.info('Alert %s: found %d raw listings', alert.id, len(all_listings))

            # Dedup and insert new DiscoveredJob records
            new_job_ids = []
            for listing in all_listings:
                excluded = preferences.get('excluded_companies', [])
                if listing.company and any(
                    ex.lower() in listing.company.lower() for ex in excluded
                ):
                    continue

                from django.utils.dateparse import parse_datetime
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
                    },
                )
                new_job_ids.append(str(job.id))

            logger.info('Alert %s: %d unique jobs saved', alert.id, len(new_job_ids))

            # Update alert timestamps
            alert.last_run_at = now
            alert.set_next_run()
            alert.save(update_fields=['last_run_at', 'next_run_at'])

            # Chain matching task
            if new_job_ids:
                match_jobs_task.delay(str(alert.id), new_job_ids)

        except Exception as exc:
            logger.exception('discover_jobs_task failed for alert %s: %s', alert.id, exc)


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

    # Deduct 1 credit for this run
    credits_used = 0
    credit_deducted = False
    try:
        deduct_credits(
            alert.user,
            'job_alert_run',
            description=f'Job alert run #{run.id}',
            reference_id=str(run.id),
        )
        credits_used = 1
        credit_deducted = True
    except InsufficientCreditsError as e:
        logger.warning('Insufficient credits for alert %s (balance=%d) — skipping run', job_alert_id, e.balance)
        run.error_message = f'Insufficient credits (balance={e.balance})'
        run.save(update_fields=['error_message'])
        return

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
        if credit_deducted:
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
