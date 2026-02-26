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
