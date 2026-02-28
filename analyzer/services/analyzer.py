import logging
import time
from decimal import Decimal

from ..models import ResumeAnalysis, LLMResponse
from .pdf_extractor import PDFExtractor
from .jd_fetcher import JDFetcher
from .ai_providers.factory import get_ai_provider

logger = logging.getLogger('analyzer')

# ── Cost estimation ─────────────────────────────────────────────────────────
# Approximate pricing per 1M tokens (USD) for common models via OpenRouter.
# Updated periodically — not exact, just for internal cost tracking.
_MODEL_PRICING = {
    'anthropic/claude-3.5-haiku': {'input': 0.80, 'output': 4.00},
    'anthropic/claude-3-haiku': {'input': 0.25, 'output': 1.25},
    'anthropic/claude-3.5-sonnet': {'input': 3.00, 'output': 15.00},
    'openai/gpt-4o-mini': {'input': 0.15, 'output': 0.60},
    'openai/gpt-4o': {'input': 2.50, 'output': 10.00},
    'google/gemini-flash-1.5': {'input': 0.075, 'output': 0.30},
}


def _estimate_cost(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> Decimal | None:
    """Estimate USD cost based on model and token counts. Returns None if unknown."""
    if not prompt_tokens or not completion_tokens:
        return None
    pricing = _MODEL_PRICING.get(model)
    if not pricing:
        # Try partial match (model name without provider prefix)
        for key, val in _MODEL_PRICING.items():
            if model in key or key in model:
                pricing = val
                break
    if not pricing:
        return None
    input_cost = Decimal(str(prompt_tokens)) * Decimal(str(pricing['input'])) / Decimal('1000000')
    output_cost = Decimal(str(completion_tokens)) * Decimal(str(pricing['output'])) / Decimal('1000000')
    return (input_cost + output_cost).quantize(Decimal('0.000001'))


class ResumeAnalyzer:
    """
    Orchestrates the full resume analysis pipeline with atomic steps:
    1. Extract text from the uploaded PDF  → commit
    2. Resolve the job description          → commit (+ ScrapeResult if URL)
    3. Call the configured AI provider      → commit LLMResponse
    4. Parse/persist analysis results       → commit final ResumeAnalysis

    Each step checks `pipeline_step` so interrupted analyses can resume
    from where they left off.
    """

    # Ordered steps — each entry is (step_name, method_name)
    _STEPS = [
        (ResumeAnalysis.STEP_PDF_EXTRACT, '_step_pdf_extract'),
        (ResumeAnalysis.STEP_JD_SCRAPE, '_step_jd_scrape'),
        (ResumeAnalysis.STEP_LLM_CALL, '_step_llm_call'),
        (ResumeAnalysis.STEP_PARSE_RESULT, '_step_parse_result'),
    ]

    # Steps that are considered "done" and should be skipped on resume
    _COMPLETED_STEPS = {ResumeAnalysis.STEP_DONE}

    def __init__(self):
        self.pdf_extractor = PDFExtractor()
        self.ai_provider = get_ai_provider()
        logger.debug('ResumeAnalyzer initialized — provider: %s', type(self.ai_provider).__name__)

    def run(self, analysis: ResumeAnalysis) -> ResumeAnalysis:
        """
        Run (or resume) the full analysis pipeline.
        Each step commits to DB before moving to the next.
        """
        pipeline_start = time.time()
        current_step = analysis.pipeline_step

        # Determine which steps to skip (already completed)
        step_order = [s[0] for s in self._STEPS]
        if current_step in self._COMPLETED_STEPS:
            logger.debug('Analysis %s is already done — nothing to do', analysis.id)
            return analysis

        # Find where to resume from
        start_idx = 0
        if current_step != ResumeAnalysis.STEP_PENDING:
            try:
                # Resume FROM the failed/interrupted step (re-run it)
                start_idx = step_order.index(current_step)
                logger.debug('Resuming analysis %s from step: %s', analysis.id, current_step)
            except ValueError:
                start_idx = 0

        analysis.status = ResumeAnalysis.STATUS_PROCESSING
        analysis.error_message = ''
        analysis.save(update_fields=['status', 'error_message'])

        for step_name, method_name in self._STEPS[start_idx:]:
            logger.debug('── Step: %s ──', step_name)
            step_start = time.time()

            method = getattr(self, method_name)
            # Each step saves pipeline_step + its own data in a single write
            method(analysis, step_name)

            logger.debug('✅ %s done (%.2fs)', step_name, time.time() - step_start)

        # Mark as complete
        analysis.pipeline_step = ResumeAnalysis.STEP_DONE
        analysis.status = ResumeAnalysis.STATUS_DONE
        analysis.save(update_fields=['pipeline_step', 'status'])

        logger.info('✅ PIPELINE COMPLETE — analysis=%s total=%.2fs', analysis.id, time.time() - pipeline_start)
        return analysis

    # ── Step 1: PDF extraction ─────────────────────────────────────────────

    def _step_pdf_extract(self, analysis: ResumeAnalysis, step_name: str):
        if analysis.resume_text:
            logger.debug('Skipping PDF extract — already have %d chars', len(analysis.resume_text))
            # Still record pipeline_step for crash recovery
            analysis.pipeline_step = step_name
            analysis.save(update_fields=['pipeline_step'])
            return

        logger.debug('Extracting text from PDF: %s', analysis.resume_file.name)
        resume_text = self.pdf_extractor.extract(analysis.resume_file)
        analysis.resume_text = resume_text
        analysis.pipeline_step = step_name
        analysis.save(update_fields=['resume_text', 'pipeline_step'])
        logger.debug('Extracted %d chars', len(resume_text))

    # ── Step 2: JD resolution ──────────────────────────────────────────────

    def _step_jd_scrape(self, analysis: ResumeAnalysis, step_name: str):
        if analysis.resolved_jd:
            logger.debug('Skipping JD resolve — already have %d chars', len(analysis.resolved_jd))
            analysis.pipeline_step = step_name
            analysis.save(update_fields=['pipeline_step'])
            return

        logger.debug('Resolving JD (type=%s)', analysis.jd_input_type)
        resolved_jd, scrape_result = self._resolve_jd(analysis)
        analysis.resolved_jd = resolved_jd
        analysis.pipeline_step = step_name
        if scrape_result:
            analysis.scrape_result = scrape_result
        analysis.save(update_fields=['resolved_jd', 'scrape_result', 'pipeline_step'])
        logger.debug('Resolved JD: %d chars', len(resolved_jd))

    # ── Step 3: LLM call ───────────────────────────────────────────────────

    def _step_llm_call(self, analysis: ResumeAnalysis, step_name: str):
        # If we already have a successful LLM response, skip
        if analysis.llm_response and analysis.llm_response.status == LLMResponse.STATUS_DONE:
            logger.debug('Skipping LLM call — already have response (id=%s)', analysis.llm_response.id)
            analysis.pipeline_step = step_name
            analysis.save(update_fields=['pipeline_step'])
            return

        logger.debug('Sending to AI provider (%s)...', type(self.ai_provider).__name__)
        logger.debug('Resume text: %d chars | JD text: %d chars', len(analysis.resume_text), len(analysis.resolved_jd))

        # Create pending LLMResponse and link to analysis in one write
        llm_resp = LLMResponse.objects.create(
            user=analysis.user,
            model_used=type(self.ai_provider).__name__,
            status=LLMResponse.STATUS_PENDING,
            call_purpose='analysis',
        )
        analysis.llm_response = llm_resp
        analysis.pipeline_step = step_name
        analysis.save(update_fields=['llm_response', 'pipeline_step'])

        try:
            result = self.ai_provider.analyze(analysis.resume_text, analysis.resolved_jd)
        except ValueError as exc:
            llm_resp.status = LLMResponse.STATUS_FAILED
            llm_resp.error_message = str(exc)
            llm_resp.save(update_fields=['status', 'error_message'])
            raise

        # Persist raw + prompt + parsed + token usage atomically
        llm_resp.prompt_sent = result.get('prompt', '')
        llm_resp.raw_response = result.get('raw', '')
        llm_resp.parsed_response = result.get('parsed')
        llm_resp.model_used = result.get('model', type(self.ai_provider).__name__)
        llm_resp.duration_seconds = result.get('duration')
        llm_resp.status = LLMResponse.STATUS_DONE

        # Token usage tracking
        usage = result.get('usage', {})
        if usage:
            llm_resp.prompt_tokens = usage.get('prompt_tokens')
            llm_resp.completion_tokens = usage.get('completion_tokens')
            llm_resp.total_tokens = usage.get('total_tokens')
            llm_resp.estimated_cost_usd = _estimate_cost(
                llm_resp.model_used, usage.get('prompt_tokens'), usage.get('completion_tokens'),
            )

        llm_resp.save(update_fields=[
            'prompt_sent', 'raw_response', 'parsed_response',
            'model_used', 'duration_seconds', 'status',
            'prompt_tokens', 'completion_tokens', 'total_tokens', 'estimated_cost_usd',
        ])
        logger.debug('LLMResponse saved (id=%s)', llm_resp.id)

    # ── Step 4: Parse & persist results ────────────────────────────────────

    def _step_parse_result(self, analysis: ResumeAnalysis, step_name: str):
        llm_resp = analysis.llm_response
        if not llm_resp or not llm_resp.parsed_response:
            raise ValueError('No parsed LLM response available to extract results from.')

        data = llm_resp.parsed_response
        scores = data.get('scores', {})
        logger.debug('Writing analysis results — grade=%s generic_ats=%s',
                     data.get('overall_grade'), scores.get('generic_ats'))

        analysis.overall_grade = data.get('overall_grade', '')
        analysis.scores = scores
        analysis.ats_disclaimers = data.get('ats_disclaimers')
        analysis.keyword_analysis = data.get('keyword_analysis')
        analysis.section_feedback = data.get('section_feedback')
        analysis.sentence_suggestions = data.get('sentence_suggestions')
        analysis.formatting_flags = data.get('formatting_flags')
        analysis.quick_wins = data.get('quick_wins')
        analysis.summary = data.get('summary', '')
        # Keep ats_score as generic_ats for dashboard stats and backward compat
        analysis.ats_score = scores.get('generic_ats')
        analysis.ai_provider_used = llm_resp.model_used

        # Populate JD metadata from LLM when not already provided by user (text/url inputs)
        job_meta = data.get('job_metadata', {})
        update_fields = [
            'overall_grade', 'scores', 'ats_disclaimers', 'keyword_analysis',
            'section_feedback', 'sentence_suggestions', 'formatting_flags',
            'quick_wins', 'summary', 'ats_score', 'ai_provider_used',
        ]

        if not analysis.jd_role and job_meta.get('job_title'):
            analysis.jd_role = job_meta['job_title'][:255]
            update_fields.append('jd_role')

        if not analysis.jd_company and job_meta.get('company'):
            analysis.jd_company = job_meta['company'][:255]
            update_fields.append('jd_company')

        if not analysis.jd_skills and job_meta.get('skills'):
            analysis.jd_skills = job_meta['skills']
            update_fields.append('jd_skills')

        if analysis.jd_experience_years is None and job_meta.get('experience_years') is not None:
            analysis.jd_experience_years = job_meta['experience_years']
            update_fields.append('jd_experience_years')

        if not analysis.jd_industry and job_meta.get('industry'):
            analysis.jd_industry = job_meta['industry'][:255]
            update_fields.append('jd_industry')

        if not analysis.jd_extra_details and job_meta.get('extra_details'):
            analysis.jd_extra_details = job_meta['extra_details']
            update_fields.append('jd_extra_details')

        analysis.pipeline_step = step_name
        update_fields.append('pipeline_step')

        analysis.save(update_fields=update_fields)
        logger.debug('✅ Results saved (grade=%s, ats=%s, role=%s, company=%s)',
                     analysis.overall_grade, analysis.ats_score, analysis.jd_role, analysis.jd_company)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_jd(self, analysis: ResumeAnalysis) -> tuple:
        """Returns (resolved_text, scrape_result_or_None)."""
        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_TEXT:
            return analysis.jd_text, None

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_URL:
            # Lazy instantiation — only create JDFetcher when we actually need Firecrawl
            jd_fetcher = JDFetcher()
            cleaned_text, scrape_result = jd_fetcher.fetch(analysis.jd_url, user=analysis.user)
            # Prefer Firecrawl's concise summary over full markdown to reduce token usage
            if scrape_result and scrape_result.summary:
                logger.debug('Using Firecrawl summary (%d chars) instead of full markdown (%d chars)',
                             len(scrape_result.summary), len(cleaned_text))
                return scrape_result.summary, scrape_result
            return cleaned_text, scrape_result

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_FORM:
            # build_from_form is a pure string builder — no Firecrawl needed
            text = JDFetcher.build_from_form(
                role=analysis.jd_role,
                company=analysis.jd_company,
                skills=analysis.jd_skills,
                experience_years=analysis.jd_experience_years,
                industry=analysis.jd_industry,
                extra_details=analysis.jd_extra_details,
            )
            return text, None

        raise ValueError(f'Unknown jd_input_type: {analysis.jd_input_type}')
