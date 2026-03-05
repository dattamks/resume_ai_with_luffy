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
def process_resume_upload_task(self, resume_id):
    """
    Phase A — Process a newly uploaded resume: extract text, run merged
    resume understanding LLM call, save parsed_content + career_profile,
    then chain embedding computation.

    Triggered automatically on resume upload (for new resumes only).
    Pipeline: PDF extract → merged LLM call → save → chain embedding.
    """
    from .models import Resume, JobSearchProfile
    from .services.pdf_extractor import PDFExtractor
    from .services.resume_understanding import understand_resume

    logger.info('process_resume_upload_task started: resume_id=%s', resume_id)

    try:
        resume = Resume.objects.get(id=resume_id)
    except Resume.DoesNotExist:
        logger.error('Resume %s not found — aborting upload processing', resume_id)
        return

    # Guard: skip if already processed
    if resume.processing_status == Resume.PROCESSING_DONE:
        logger.info('Resume %s already processed — skipping', resume_id)
        return

    # Mark as processing
    resume.processing_status = Resume.PROCESSING_PROCESSING
    resume.save(update_fields=['processing_status'])

    try:
        # Step 1: Extract text from PDF
        extractor = PDFExtractor()
        resume_text = extractor.extract(resume.file)
        if not resume_text or len(resume_text.strip()) < 50:
            raise ValueError(
                f'Resume {resume_id} has insufficient text ({len(resume_text or "")} chars). '
                'Upload a readable PDF.'
            )
        resume.resume_text = resume_text
        resume.save(update_fields=['resume_text'])
        logger.info('PDF text extracted: resume=%s chars=%d', resume_id, len(resume_text))

        # Step 2: Merged LLM call — resume understanding
        result = understand_resume(resume_text)

        # Step 3: Save results
        resume.parsed_content = result['resume_data']
        resume.career_profile = result['career_profile']
        resume.processing_status = Resume.PROCESSING_DONE
        resume.processing_error = ''
        resume.save(update_fields=[
            'parsed_content', 'career_profile',
            'processing_status', 'processing_error',
        ])
        logger.info(
            'Resume understanding complete: resume=%s name=%s seniority=%s',
            resume_id,
            result['resume_data'].get('contact', {}).get('name', '?'),
            result['career_profile'].get('seniority', '?'),
        )

        # Step 4: Upsert JobSearchProfile from career_profile (DB copy, no LLM)
        cp = result['career_profile']
        JobSearchProfile.objects.update_or_create(
            resume=resume,
            defaults={
                'titles': cp.get('titles', []),
                'skills': cp.get('skills', []),
                'seniority': cp.get('seniority', 'mid'),
                'industries': cp.get('industries', []),
                'locations': cp.get('locations', []),
                'experience_years': cp.get('experience_years'),
                'raw_extraction': result.get('raw', ''),
            },
        )
        logger.info('JobSearchProfile upserted from upload processing: resume=%s', resume_id)

        # Step 5: Chain embedding computation
        compute_resume_embedding_task.delay(str(resume_id))

    except ValueError as exc:
        logger.warning('Resume upload processing failed (resume=%s): %s', resume_id, exc)
        resume.processing_status = Resume.PROCESSING_FAILED
        resume.processing_error = str(exc)
        resume.save(update_fields=['processing_status', 'processing_error'])
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception('Unexpected error in resume upload processing (resume=%s)', resume_id)
        resume.processing_status = Resume.PROCESSING_FAILED
        resume.processing_error = str(exc)[:500]
        resume.save(update_fields=['processing_status', 'processing_error'])
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


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

        # Sync analyzed job to local DiscoveredJob DB + crawler bot (fire-and-forget)
        sync_analyzed_job_task.delay(analysis_id)

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


# ══════════════════════════════════════════════════════════════════════════════
# Sync analyzed jobs to local DiscoveredJob + Crawler Bot
# ══════════════════════════════════════════════════════════════════════════════

_SOURCE_USER_ANALYSIS = 'user_analysis'


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=20,
    acks_late=True,
    ignore_result=True,
)
def sync_analyzed_job_task(self, analysis_id):
    """
    After a successful resume analysis, save the JD as a DiscoveredJob
    in our own DB and push it to the Crawler Bot ingest API so both
    databases stay in sync.

    Fires as a fire-and-forget Celery task from ``run_analysis_task``.
    Only runs when the analysis has a ``jd_url`` (URL-based JD input).
    For text/form-based JDs we still create a local DiscoveredJob if
    we have enough metadata (title + company).
    """
    from .models import ResumeAnalysis, DiscoveredJob

    try:
        analysis = ResumeAnalysis.objects.get(id=analysis_id)
    except ResumeAnalysis.DoesNotExist:
        logger.warning('sync_analyzed_job_task: analysis %s not found', analysis_id)
        return

    if analysis.status != ResumeAnalysis.STATUS_DONE:
        return

    # Need at minimum a title to create a useful job record
    title = (analysis.jd_role or '').strip()
    company = (analysis.jd_company or '').strip()
    jd_url = (analysis.jd_url or '').strip()

    if not title:
        logger.debug('sync_analyzed_job: skipped — no jd_role for analysis %s', analysis_id)
        return

    # ── Parse skills from comma-separated string ────────────────────
    skills_raw = analysis.jd_skills or ''
    skills_list = [s.strip() for s in skills_raw.split(',') if s.strip()] if skills_raw else []

    # ── Build the external_id (dedup key) ──────────────────────────
    # For URL-based: use the URL itself
    # For text/form-based: use "analysis:<analysis_id>"
    if jd_url:
        external_id = jd_url
    else:
        external_id = f'analysis:{analysis_id}'

    # ── 1. Save to local DiscoveredJob DB ──────────────────────────
    job_data = {
        'title': title[:500],
        'company': company[:255],
        'url': jd_url or f'https://iluffy.app/analyses/{analysis_id}/',
        'source': _SOURCE_USER_ANALYSIS,
        'description_snippet': (analysis.resolved_jd or '')[:500],
        'skills_required': skills_list,
        'industry': (analysis.jd_industry or '')[:100],
    }

    if analysis.jd_experience_years is not None:
        job_data['experience_years_min'] = analysis.jd_experience_years

    try:
        job, created = DiscoveredJob.objects.update_or_create(
            source=_SOURCE_USER_ANALYSIS,
            external_id=external_id,
            defaults=job_data,
        )

        # Compute embedding if missing
        if created and hasattr(DiscoveredJob, 'embedding') and not job.embedding:
            try:
                from .services.embedding_service import compute_embedding
                text = f"{title} at {company}. {(analysis.resolved_jd or '')[:500]}"
                job.embedding = compute_embedding(text)
                job.save(update_fields=['embedding'])
            except Exception as emb_exc:
                logger.warning('sync_analyzed_job: embedding failed for job %s: %s', job.id, emb_exc)

        action = 'created' if created else 'updated'
        logger.info(
            'sync_analyzed_job: %s DiscoveredJob %s — "%s" @ %s (analysis=%s)',
            action, job.id, title, company, analysis_id,
        )

        # Skill enrichment
        try:
            _enrich_skills_from_jobs([job], source_label='sync_analyzed_job')
        except Exception as skill_exc:
            logger.warning('sync_analyzed_job: skill enrichment failed: %s', skill_exc)
    except Exception as exc:
        logger.error('sync_analyzed_job: failed to save DiscoveredJob: %s', exc)

    # ── 2. Push to Crawler Bot ─────────────────────────────────────
    try:
        from .services.crawler_bot_client import get_crawler_bot_client
        client = get_crawler_bot_client()
        if not client:
            logger.debug('sync_analyzed_job: crawler bot not configured — skipping push')
            return

        # Push company first (skeleton — crawler bot will enrich later)
        if company:
            try:
                client.push_company({
                    'name': company,
                    'industry': analysis.jd_industry or '',
                })
                logger.debug('sync_analyzed_job: pushed company "%s" to crawler bot', company)
            except Exception as co_exc:
                # Non-fatal — the job push will auto-create a skeleton company
                logger.debug('sync_analyzed_job: company push failed (non-fatal): %s', co_exc)

        # Push job
        crawler_job_data = {
            'url': jd_url or f'https://iluffy.app/analyses/{analysis_id}/',
            'title': title,
            'company': company or 'Unknown',
            'description_snippet': (analysis.resolved_jd or '')[:500],
            'skills_required': skills_list,
            'industry': analysis.jd_industry or '',
            'source_type': 'career_page' if jd_url else 'job_listing_site',
        }

        if analysis.jd_experience_years is not None:
            crawler_job_data['experience_years_min'] = analysis.jd_experience_years

        result = client.push_job(crawler_job_data)
        logger.info(
            'sync_analyzed_job: pushed job to crawler bot — id=%s title="%s" (analysis=%s)',
            result.get('id', '?'), title, analysis_id,
        )
    except Exception as exc:
        logger.warning('sync_analyzed_job: crawler bot push failed: %s', exc)
        # Don't retry for crawler bot failures — local DB is already saved


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

        # Step 6: Create a usable Resume from the generated output
        _create_resume_from_generated(gen, result['parsed'], file_bytes, ext)

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


def _create_resume_from_generated(gen, resume_content, file_bytes, ext):
    """
    Create a full Resume record from a completed GeneratedResume.

    The generated resume becomes a first-class Resume that can be used
    for new analyses, job alerts, feed, etc. — no second LLM call needed
    since we already have structured data from the generation.

    Steps:
    1. Render PDF if the original format was DOCX (Resume needs a PDF)
    2. Create Resume with parsed_content + career_profile from resume_content
    3. Mark as PROCESSING_DONE (skip process_resume_upload_task)
    4. Create JobSearchProfile from career_profile
    5. Link back to the GeneratedResume
    6. Chain embedding computation
    """
    import hashlib
    from .models import Resume, JobSearchProfile, ResumeVersion
    from .services.template_registry import get_renderer

    user = gen.user

    try:
        # Step 1: Ensure we have a PDF for the Resume file
        if ext != 'pdf':
            pdf_renderer = get_renderer(gen.template, 'pdf')
            pdf_bytes = pdf_renderer(resume_content)
        else:
            pdf_bytes = file_bytes

        # Step 2: Build parsed_content and career_profile from resume_content
        # resume_content has: contact, summary, experience, education, skills, etc.
        # This IS the parsed_content — same schema.
        parsed_content = resume_content

        # Build career_profile from the structured data
        career_profile = _build_career_profile(resume_content, gen.analysis)

        # Compute file hash for dedup
        file_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # Check if this exact file already exists for the user
        existing = Resume.objects.filter(user=user, file_hash=file_hash).first()
        if existing:
            # Same content already exists — just link it
            gen.resume = existing
            gen.save(update_fields=['resume'])
            logger.info(
                'Generated resume %s linked to existing Resume %s (same hash)',
                gen.id, existing.id,
            )
            return

        # Step 3: Create the Resume record
        contact = resume_content.get('contact', {})
        contact_name = contact.get('name', 'Generated Resume')
        role = (gen.analysis.jd_role if gen.analysis else 'general').strip() or 'general'
        original_filename = f"{contact_name.replace(' ', '_')}_{role.replace(' ', '_')}_generated.pdf"

        resume = Resume(
            user=user,
            file_hash=file_hash,
            original_filename=original_filename[:255],
            file_size_bytes=len(pdf_bytes),
            # Pre-populate with structured data — skip LLM understanding
            parsed_content=parsed_content,
            career_profile=career_profile,
            resume_text=_resume_content_to_text(resume_content),
            processing_status=Resume.PROCESSING_DONE,
        )
        resume.file.save(
            f'resumes/{original_filename[:200]}',
            ContentFile(pdf_bytes),
            save=False,
        )
        resume.save()

        # Create version history entry
        ResumeVersion.objects.create(
            user=user,
            resume=resume,
            version_number=1,
            change_summary=f'AI-generated from analysis (template: {gen.template})',
        )

        # Auto-set as default if user has no default resume
        if not Resume.objects.filter(user=user, is_default=True).exists():
            resume.is_default = True
            resume.save(update_fields=['is_default'])

        # Step 4: Create JobSearchProfile from career_profile
        if career_profile:
            JobSearchProfile.objects.update_or_create(
                resume=resume,
                defaults={
                    'titles': career_profile.get('titles', []),
                    'skills': career_profile.get('skills', []),
                    'seniority': career_profile.get('seniority', 'mid'),
                    'industries': career_profile.get('industries', []),
                    'locations': career_profile.get('locations', []),
                    'experience_years': career_profile.get('experience_years'),
                    'raw_extraction': career_profile,
                },
            )

        # Step 5: Link the Resume back to the GeneratedResume
        gen.resume = resume
        gen.save(update_fields=['resume'])

        logger.info(
            'Resume created from generated output: gen=%s resume=%s filename=%s',
            gen.id, resume.id, original_filename,
        )

        # Step 6: Chain embedding computation
        compute_resume_embedding_task.delay(str(resume.id))

    except Exception:
        logger.exception(
            'Failed to create Resume from GeneratedResume %s — '
            'generated resume is still usable, Resume creation is best-effort',
            gen.id,
        )


def _build_career_profile(resume_content, analysis=None):
    """
    Derive career_profile from structured resume_content + analysis context.

    Returns dict with: titles, skills, seniority, industries, locations, experience_years.
    """
    contact = resume_content.get('contact', {})
    experience = resume_content.get('experience', [])
    skills_data = resume_content.get('skills', {})

    # Extract titles from experience
    titles = []
    if analysis and analysis.jd_role:
        titles.append(analysis.jd_role)
    for exp in experience[:3]:
        title = exp.get('title', '')
        if title and title not in titles:
            titles.append(title)

    # Extract skills (flatten grouped skills)
    skills = []
    if isinstance(skills_data, dict):
        for category_skills in skills_data.values():
            if isinstance(category_skills, list):
                skills.extend(str(s) for s in category_skills if s)
    elif isinstance(skills_data, list):
        skills = [str(s) for s in skills_data if s]

    # Estimate seniority from experience count & years
    years = 0
    if experience:
        years = len(experience) * 2  # rough estimate: 2 years per role
        # Check for years in date fields
        for exp in experience:
            start = exp.get('start_date', '')
            if 'present' in str(start).lower() or 'current' in str(start).lower():
                years = max(years, len(experience) * 2)

    seniority = 'mid'
    if years >= 10:
        seniority = 'lead'
    elif years >= 6:
        seniority = 'senior'
    elif years <= 2:
        seniority = 'junior'

    # Extract locations
    locations = []
    loc = contact.get('location', '')
    if loc:
        locations.append(loc)
    for exp in experience[:2]:
        exp_loc = exp.get('location', '')
        if exp_loc and exp_loc not in locations:
            locations.append(exp_loc)

    return {
        'titles': titles[:5],
        'skills': skills[:20],
        'seniority': seniority,
        'industries': [],  # not reliably derivable without LLM
        'locations': locations[:5],
        'experience_years': years if years > 0 else None,
    }


def _resume_content_to_text(resume_content):
    """
    Convert structured resume_content JSON to plain text.
    Used for embedding computation and text-based processing.
    """
    parts = []

    contact = resume_content.get('contact', {})
    if contact.get('name'):
        parts.append(contact['name'])
    if contact.get('email'):
        parts.append(contact['email'])
    if contact.get('phone'):
        parts.append(contact['phone'])
    if contact.get('location'):
        parts.append(contact['location'])

    summary = resume_content.get('summary', '')
    if summary:
        parts.append(f"\nSUMMARY\n{summary}")

    for exp in resume_content.get('experience', []):
        title = exp.get('title', '')
        company = exp.get('company', '')
        location = exp.get('location', '')
        dates = f"{exp.get('start_date', '')} - {exp.get('end_date', '')}".strip(' -')
        parts.append(f"\n{title} | {company} | {location} | {dates}")
        for bullet in exp.get('bullets', []):
            parts.append(f"  - {bullet}")

    edu_items = resume_content.get('education', [])
    if edu_items:
        parts.append("\nEDUCATION")
        for edu in edu_items:
            degree = edu.get('degree', '')
            institution = edu.get('institution', '')
            year = edu.get('year', '')
            parts.append(f"  {degree} | {institution} | {year}")

    skills_data = resume_content.get('skills', {})
    if skills_data:
        parts.append("\nSKILLS")
        if isinstance(skills_data, dict):
            for category, skill_list in skills_data.items():
                if isinstance(skill_list, list):
                    parts.append(f"  {category}: {', '.join(str(s) for s in skill_list)}")
        elif isinstance(skills_data, list):
            parts.append(f"  {', '.join(str(s) for s in skills_data)}")

    for cert in resume_content.get('certifications', []):
        name = cert.get('name', '')
        issuer = cert.get('issuer', '')
        parts.append(f"  {name} | {issuer}")

    return '\n'.join(parts)


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

        # Create a usable Resume from the builder output
        _create_resume_from_generated(gen, gen.resume_content, file_bytes, ext)

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
    Extract a job search profile from a resume.

    Phase A: Now a DB copy from Resume.career_profile instead of an LLM call.
    Falls back to LLM extraction only if Resume.career_profile is not yet
    available (e.g. resume uploaded before Phase A was deployed).

    Triggered automatically when a JobAlert is created.
    Saves (or updates) the JobSearchProfile OneToOne record for the resume.
    """
    from .models import Resume, JobSearchProfile

    logger.info('Job search profile extraction started: resume_id=%s', resume_id)

    try:
        resume = Resume.objects.get(id=resume_id)
    except Resume.DoesNotExist:
        logger.error('Resume %s not found — aborting profile extraction', resume_id)
        return

    try:
        # Phase A: prefer career_profile from upload-time processing
        if resume.career_profile:
            cp = resume.career_profile
            profile, _ = JobSearchProfile.objects.update_or_create(
                resume=resume,
                defaults={
                    'titles': cp.get('titles', []),
                    'skills': cp.get('skills', []),
                    'seniority': cp.get('seniority', 'mid'),
                    'industries': cp.get('industries', []),
                    'locations': cp.get('locations', []),
                    'experience_years': cp.get('experience_years'),
                    'raw_extraction': cp,
                },
            )
            logger.info(
                'JobSearchProfile saved (from career_profile): resume=%s seniority=%s titles=%s',
                resume_id, profile.seniority, profile.titles[:2],
            )
            # Chain embedding computation
            compute_resume_embedding_task.delay(str(resume_id))
            return

        # No career_profile available — resume was uploaded before Phase A.
        # Trigger process_resume_upload_task to populate it, then retry.
        logger.warning(
            'Resume %s has no career_profile — triggering upload processing',
            resume_id,
        )
        process_resume_upload_task.delay(str(resume_id))
        raise self.retry(
            exc=ValueError('career_profile not yet available'),
            countdown=30,
        )

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
    Creates JobMatch records for jobs scoring ≥ threshold.
    Chains send_job_alert_notification_task on completion.

    Phase E: Uses embedding matcher instead of LLM-based job_matcher.
    """
    import time as _time
    from django.utils import timezone
    from .models import JobAlert, DiscoveredJob, JobMatch, JobAlertRun
    from .services.embedding_matcher import match_jobs_for_alert

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

    try:
        discovered_jobs = DiscoveredJob.objects.filter(id__in=discovered_job_ids)
        run.jobs_discovered = discovered_jobs.count()

        # Use embedding matcher (Phase E — replaces LLM-based match_jobs)
        scored = match_jobs_for_alert(alert, job_ids=discovered_job_ids)

        # Build a map: DiscoveredJob.id → DiscoveredJob
        job_map = {str(j.id): j for j in discovered_jobs}

        matches_created = 0
        for item in scored:
            # Embedding matcher already filters by threshold
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
        run.credits_used = 0
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
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
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

    # Skill enrichment for newly crawled jobs
    if new_job_ids:
        try:
            enrichment_jobs = list(DiscoveredJob.objects.filter(id__in=new_job_ids))
            _enrich_skills_from_jobs(enrichment_jobs, source_label='crawl_jobs_daily_task')
        except Exception as exc:
            logger.warning('crawl_jobs_daily_task: skill enrichment failed: %s', exc)

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


# ── Ingest Pipeline: Embed + Match ───────────────────────────────────────────

# Max jobs to embed in a single API call (OpenAI batch limit)
_EMBED_BATCH_SIZE = 100
# Lock TTL for match_all_alerts_task dedup (seconds)
_MATCH_LOCK_TTL = 300  # 5 minutes


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
    ignore_result=True,
)
def process_ingested_jobs_task(self, job_ids):
    """
    Process newly ingested jobs from the Crawler Bot ingest API.

    Triggered by ``JobIngestView`` and ``JobBulkIngestView`` when new
    ``DiscoveredJob`` records are created (not on updates).

    Args:
        job_ids: List of DiscoveredJob UUID strings, OR ``None`` to
                 drain the Redis queue populated by single-job ingests.

    Pipeline:
    1. Compute pgvector embeddings for new jobs **in batches**
       (single API call per batch of 100 — not one call per job)
    2. Chain ``match_all_alerts_task`` with a Redis dedup lock to
       prevent concurrent matching storms when the bot sends many
       bulk requests in quick succession

    This closes the gap where bot-ingested jobs were saved to the DB
    but never embedded or matched against user profiles.
    """
    import time as _time
    from .models import DiscoveredJob

    # If job_ids is None, drain the Redis queue (debounced single-job ingests)
    if job_ids is None:
        queue_key = 'ingest:pending_job_ids'
        raw = cache.get(queue_key, '')
        cache.delete(queue_key)
        cache.delete('ingest:pending_job_ids:scheduled')
        job_ids = [jid.strip() for jid in raw.split(',') if jid.strip()]

    if not job_ids:
        return

    start = _time.monotonic()
    logger.info('process_ingested_jobs_task: processing %d new jobs', len(job_ids))

    # Step 1: Compute embeddings in batches (if pgvector is available)
    embedded_count = 0
    if hasattr(DiscoveredJob, 'embedding'):
        # Load all jobs at once
        jobs = list(
            DiscoveredJob.objects.filter(id__in=job_ids)
            .values_list('id', 'title', 'company', 'description_snippet')
        )

        # Process in batches of _EMBED_BATCH_SIZE
        for batch_start in range(0, len(jobs), _EMBED_BATCH_SIZE):
            batch = jobs[batch_start:batch_start + _EMBED_BATCH_SIZE]

            # Build text representations for the batch
            texts = []
            batch_ids = []
            for job_id, title, company, snippet in batch:
                parts = [title or '']
                if company:
                    parts.append(f'at {company}')
                if snippet:
                    parts.append((snippet or '')[:500])
                text = ' | '.join(parts)
                if text.strip():
                    texts.append(text)
                    batch_ids.append(job_id)

            if not texts:
                continue

            try:
                from .services.embedding_service import compute_embeddings_batch
                embeddings = compute_embeddings_batch(texts)

                # Bulk-update embeddings
                for job_id, embedding in zip(batch_ids, embeddings):
                    if embedding is not None:
                        try:
                            DiscoveredJob.objects.filter(id=job_id).update(
                                embedding=embedding,
                            )
                            embedded_count += 1
                        except Exception as exc:
                            logger.warning(
                                'process_ingested_jobs_task: failed to save embedding for job %s: %s',
                                job_id, exc,
                            )
            except Exception as exc:
                logger.warning(
                    'process_ingested_jobs_task: batch embedding failed (batch starting at %d): %s',
                    batch_start, exc,
                )
                # Fall back to single embeddings for this batch
                from .services.embedding_service import compute_job_embedding
                for job_id, title, company, snippet in batch:
                    try:
                        embedding = compute_job_embedding(
                            title=title or '',
                            company=company or '',
                            description=snippet or '',
                        )
                        DiscoveredJob.objects.filter(id=job_id).update(embedding=embedding)
                        embedded_count += 1
                    except Exception:
                        pass  # Already logged at batch level
    else:
        logger.info('process_ingested_jobs_task: pgvector not available — skipping embeddings')

    duration = _time.monotonic() - start
    logger.info(
        'process_ingested_jobs_task: embedded %d/%d jobs in %.2fs',
        embedded_count, len(job_ids), duration,
    )

    # Step 2: Skill enrichment — upsert Skill rows + dispatch LLM for new ones
    try:
        enrichment_jobs = list(DiscoveredJob.objects.filter(id__in=job_ids))
        _enrich_skills_from_jobs(enrichment_jobs, source_label='process_ingested_jobs_task')
    except Exception as exc:
        logger.warning('process_ingested_jobs_task: skill enrichment failed: %s', exc)

    # Step 3: Chain matching — use Redis lock to prevent concurrent storms
    # If another process_ingested_jobs_task already scheduled matching,
    # the lock prevents a redundant run. The first match run will pick up
    # all newly embedded jobs anyway.
    lock_key = 'lock:match_all_alerts_after_ingest'
    if cache.add(lock_key, 1, timeout=_MATCH_LOCK_TTL):
        logger.info('process_ingested_jobs_task: acquired match lock — chaining match_all_alerts_task')
        match_all_alerts_task.delay()
    else:
        logger.info(
            'process_ingested_jobs_task: match lock already held — '
            'skipping redundant match_all_alerts_task (another run will cover these jobs)'
        )


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

    # Release the ingest match lock so future ingestions can trigger matching
    cache.delete('lock:match_all_alerts_after_ingest')


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
    except Exception as exc:
        logger.exception('Unexpected error in interview prep: id=%s', prep.id)
        prep.status = InterviewPrep.STATUS_FAILED
        prep.error_message = str(exc)
        prep.save(update_fields=['status', 'error_message'])
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


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

    except Exception as exc:
        logger.exception('Unexpected error in cover letter: id=%s', cl.id)
        cl.status = CoverLetter.STATUS_FAILED
        cl.error_message = str(exc)
        cl.save(update_fields=['status', 'error_message'])
        if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════════════════
#  Role Family Generation (hybrid role scoping for feed/insights)
# ═══════════════════════════════════════════════════════════════════════════


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=120,
    acks_late=True,
)
def generate_role_family_task(self, source_titles: list[str]):
    """
    Generate and store a RoleFamily mapping via LLM.

    Given a list of source job titles (from a user's JobSearchProfile),
    asks the LLM to produce 10-15 related/synonym job titles.  The result
    is stored in the RoleFamily model, keyed by a SHA-256 hash of the
    normalised titles so it can be shared across users with the same roles.

    Skips the LLM call if a fresh mapping (< 30 days) already exists.
    """
    import json
    import re
    import time

    from .models import RoleFamily
    from .services.ai_providers.factory import get_openai_client, llm_retry
    from .services.ai_providers.json_repair import repair_json

    if not source_titles:
        logger.info('generate_role_family_task: empty titles — skipping')
        return

    titles_hash = RoleFamily.compute_hash(source_titles)

    # Check if a fresh mapping already exists
    try:
        existing = RoleFamily.objects.get(titles_hash=titles_hash)
        age_days = (timezone.now() - existing.generated_at).days
        if age_days < 30:
            logger.info(
                'RoleFamily already fresh (%d days old) for titles=%s — skipping LLM',
                age_days, source_titles,
            )
            return
    except RoleFamily.DoesNotExist:
        pass

    # Build prompt
    titles_str = ', '.join(f'"{t}"' for t in source_titles)
    user_prompt = (
        f'Given these job titles from a user\'s resume: [{titles_str}]\n\n'
        'List 10-15 closely related job titles that:\n'
        '1. Require similar skills and qualifications\n'
        '2. A person with these titles would be qualified for or interested in\n'
        '3. Include common variations, synonyms, and abbreviations '
        '(e.g. "SDE" for "Software Development Engineer")\n'
        '4. Span common variations across seniority where the core role is the same '
        '(e.g. "Senior Data Analyst" if source is "Data Analyst")\n\n'
        'Return ONLY a JSON array of strings. No explanations, no markdown.\n'
        'Example: ["Business Analyst", "BI Analyst", "Product Analyst"]'
    )

    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    if not api_key:
        logger.warning('generate_role_family_task: OPENROUTER_API_KEY not configured')
        return

    client = get_openai_client()
    messages = [
        {
            'role': 'system',
            'content': (
                'You are a job market expert. You know all job title variations, '
                'synonyms, and how roles relate across industries. '
                'Return ONLY valid JSON arrays of strings.'
            ),
        },
        {'role': 'user', 'content': user_prompt},
    ]

    logger.info('RoleFamily LLM call: titles=%s model=%s', source_titles, model)
    req_start = time.time()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=512,
            temperature=0.3,
            timeout=30,
        )

    try:
        response = _call()
        raw = response.choices[0].message.content.strip()
        duration = round(time.time() - req_start, 2)

        # Parse JSON array — strip markdown fences if present
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', raw)
        cleaned = re.sub(r'\n?\s*```$', '', cleaned)

        try:
            related = json.loads(cleaned)
        except json.JSONDecodeError:
            repaired = repair_json(cleaned)
            related = json.loads(repaired)

        if not isinstance(related, list):
            logger.warning('RoleFamily LLM returned non-list: %s', type(related))
            related = []

        # Normalise: keep only non-empty strings, deduplicate vs source titles
        source_lower = {t.strip().lower() for t in source_titles}
        related = [
            t.strip() for t in related
            if isinstance(t, str) and t.strip() and t.strip().lower() not in source_lower
        ]

        # Upsert
        RoleFamily.objects.update_or_create(
            titles_hash=titles_hash,
            defaults={
                'source_titles': [t.strip() for t in source_titles],
                'related_titles': related,
            },
        )

        logger.info(
            'RoleFamily saved: titles=%s related=%d duration=%.2fs',
            source_titles, len(related), duration,
        )

    except Exception as exc:
        logger.exception(
            'RoleFamily LLM failed: titles=%s error=%s', source_titles, exc,
        )
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════════════════
#  Skill Enrichment — LLM descriptions for newly discovered skills
# ═══════════════════════════════════════════════════════════════════════════


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    autoretry_for=(ConnectionError, OSError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=120,
    acks_late=True,
    ignore_result=True,
)
def enrich_new_skills_task(self, skill_names: list[str]):
    """
    Generate LLM descriptions, categories, display names, and roles for
    newly created Skill rows.

    Called automatically from the job ingestion pipeline when new skills
    are discovered.  Processes skills in a single LLM batch call.
    """
    import json
    import time

    from .models import Skill
    from .management.commands.aggregate_skills import (
        _generate_descriptions_batch,
    )

    if not skill_names:
        return

    # Only process skills that still lack a description
    needs_desc = list(
        Skill.objects.filter(
            name__in=skill_names,
            is_active=True,
        ).filter(
            models_Q(description='') | models_Q(description__isnull=True),
        ).values_list('name', flat=True)
    )

    if not needs_desc:
        logger.info('enrich_new_skills_task: all %d skills already have descriptions', len(skill_names))
        return

    logger.info('enrich_new_skills_task: generating descriptions for %d new skills', len(needs_desc))

    # Process in batches of 30
    batch_size = 30
    enriched = 0
    for i in range(0, len(needs_desc), batch_size):
        batch = needs_desc[i:i + batch_size]
        try:
            results = _generate_descriptions_batch(batch)
        except Exception as exc:
            logger.warning('enrich_new_skills_task: LLM batch failed: %s', exc)
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            continue

        for item in results:
            if not isinstance(item, dict) or 'name' not in item:
                continue
            name = item['name'].strip().lower()
            try:
                skill_obj = Skill.objects.get(name=name)
            except Skill.DoesNotExist:
                continue

            save_fields = ['updated_at']
            if item.get('description') and not skill_obj.description:
                skill_obj.description = item['description']
                save_fields.append('description')
            if item.get('display_name'):
                skill_obj.display_name = item['display_name']
                save_fields.append('display_name')
            if item.get('category') and item['category'] in dict(Skill.CATEGORY_CHOICES):
                skill_obj.category = item['category']
                save_fields.append('category')
            if item.get('roles') and isinstance(item['roles'], list):
                skill_obj.roles = item['roles']
                save_fields.append('roles')

            skill_obj.save(update_fields=save_fields)
            enriched += 1

        # Rate-limit between batches
        if i + batch_size < len(needs_desc):
            time.sleep(1)

    logger.info('enrich_new_skills_task: enriched %d/%d skills', enriched, len(needs_desc))


def _enrich_skills_from_jobs(jobs, source_label='pipeline'):
    """
    Helper called from pipeline tasks.  Upserts Skill rows for all jobs,
    then dispatches an async task to LLM-generate descriptions for any
    new skills.
    """
    from .services.skill_enrichment import upsert_skills_for_jobs

    new_skill_names = upsert_skills_for_jobs(jobs)
    if new_skill_names:
        logger.info(
            '%s: %d new skills found — dispatching LLM enrichment',
            source_label, len(new_skill_names),
        )
        enrich_new_skills_task.delay(new_skill_names)
    return new_skill_names


# We need Q imported for the task above
from django.db.models import Q as models_Q  # noqa: E402


# ── Admin Daily Digest ───────────────────────────────────────────────────────


@shared_task(ignore_result=True)
def send_admin_digest_task():
    """
    Periodic task (Celery Beat, twice daily — 9 AM + 11 PM IST):
    Compute 40+ platform metrics and email them to ADMIN_DIGEST_EMAILS.
    """
    from accounts.email_utils import send_templated_email
    from .services.admin_digest import compute_digest_metrics

    recipients = getattr(settings, 'ADMIN_DIGEST_EMAILS', [])
    if not recipients:
        logger.warning('send_admin_digest_task: ADMIN_DIGEST_EMAILS is empty — skipping')
        return

    try:
        metrics = compute_digest_metrics()
    except Exception:
        logger.exception('send_admin_digest_task: failed to compute metrics')
        return

    # Flatten metrics into template context
    ctx = {
        'report_time_ist': metrics['report_time_ist'],
        'period': metrics['period'],
        # Users
        'new_signups': metrics['users']['new_signups'],
        'total_users': metrics['users']['total_users'],
        'dau': metrics['users']['dau'],
        'plan_distribution': metrics['users']['plan_distribution'],
        'auth_providers': metrics['users']['auth_providers'],
        # Revenue
        'captured_count': metrics['revenue']['captured_count'],
        'captured_total_inr': metrics['revenue']['captured_total_inr'],
        'failed_payments': metrics['revenue']['failed_payments'],
        'new_subscriptions': metrics['revenue']['new_subscriptions'],
        'subscription_status': metrics['revenue']['subscription_status'],
        'webhooks_received': metrics['revenue']['webhooks_received'],
        # Credits
        'plan_credits_granted': metrics['credits']['plan_credits_granted'],
        'topup_credits': metrics['credits']['topup_credits'],
        'credits_consumed': metrics['credits']['credits_consumed'],
        'credits_refunded': metrics['credits']['credits_refunded'],
        'admin_adjustments': metrics['credits']['admin_adjustments'],
        'zero_balance_users': metrics['credits']['zero_balance_users'],
        # Analyses
        'analyses_total': metrics['analyses']['total'],
        'analyses_done': metrics['analyses']['done'],
        'analyses_failed': metrics['analyses']['failed'],
        'analyses_processing': metrics['analyses']['processing'],
        'analyses_pending': metrics['analyses']['pending'],
        'avg_ats_score': metrics['analyses']['avg_ats_score'],
        'avg_overall_grade': metrics['analyses']['avg_overall_grade'],
        # Resumes
        'resumes_uploaded': metrics['resumes']['uploaded'],
        'resume_processing_status': metrics['resumes']['processing_status'],
        'resumes_generated': metrics['resumes']['generated'],
        'generated_by_format': metrics['resumes']['generated_by_format'],
        'builder_sessions': metrics['resumes']['builder_sessions'],
        'builder_by_status': metrics['resumes']['builder_by_status'],
        # LLM
        'llm_total_calls': metrics['llm']['total_calls'],
        'llm_by_purpose': metrics['llm']['by_purpose'],
        'llm_prompt_tokens': metrics['llm']['prompt_tokens'],
        'llm_completion_tokens': metrics['llm']['completion_tokens'],
        'llm_total_tokens': metrics['llm']['total_tokens'],
        'llm_cost_usd': metrics['llm']['estimated_cost_usd'],
        'llm_avg_duration': metrics['llm']['avg_duration_sec'],
        'llm_failed': metrics['llm']['failed'],
        'llm_failure_rate': metrics['llm']['failure_rate_pct'],
        # Job Alerts
        'alert_runs': metrics['job_alerts']['alert_runs'],
        'jobs_discovered': metrics['job_alerts']['jobs_discovered'],
        'jobs_matched': metrics['job_alerts']['jobs_matched'],
        'new_discovered_jobs': metrics['job_alerts']['new_discovered_jobs'],
        'new_matches': metrics['job_alerts']['new_matches'],
        'avg_relevance_score': metrics['job_alerts']['avg_relevance_score'],
        'alerts_sent_email': metrics['job_alerts']['alerts_sent_email'],
        'alerts_sent_in_app': metrics['job_alerts']['alerts_sent_in_app'],
        'active_alerts_total': metrics['job_alerts']['active_alerts_total'],
        # Features
        'interview_preps': metrics['features']['interview_preps'],
        'cover_letters': metrics['features']['cover_letters'],
        'total_actions_today': metrics['features']['total_actions_today'],
        'action_breakdown': metrics['features']['action_breakdown'],
        # News
        'news_synced': metrics['news']['synced_today'],
        'news_by_category': metrics['news']['by_category'],
        'news_flagged': metrics['news']['flagged'],
        'news_unapproved': metrics['news']['unapproved'],
        # Notifications
        'notifications_created': metrics['notifications']['created_today'],
        'unread_total': metrics['notifications']['unread_total'],
        'contact_submissions': metrics['notifications']['contact_submissions'],
        # Infra
        'stale_crawl_sources': metrics['infra']['stale_crawl_sources'],
        'total_crawl_sources': metrics['infra']['total_crawl_sources'],
    }

    sent = 0
    for email_addr in recipients:
        try:
            send_templated_email(
                slug='admin-daily-digest',
                recipient=email_addr,
                context=ctx,
                fail_silently=False,
            )
            sent += 1
        except Exception:
            logger.exception('Admin digest failed for %s', email_addr)

    logger.info('Admin digest sent to %d/%d recipients', sent, len(recipients))