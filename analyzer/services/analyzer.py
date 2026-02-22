import time

from ..models import ResumeAnalysis, LLMResponse
from .pdf_extractor import PDFExtractor
from .jd_fetcher import JDFetcher
from .ai_providers.factory import get_ai_provider


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
        self.jd_fetcher = JDFetcher()
        self.ai_provider = get_ai_provider()
        print(f'[DEBUG] ResumeAnalyzer initialized — provider: {type(self.ai_provider).__name__}')

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
            print(f'[DEBUG] Analysis {analysis.id} is already done — nothing to do')
            return analysis

        # Find where to resume from
        start_idx = 0
        if current_step != ResumeAnalysis.STEP_PENDING:
            try:
                # Resume FROM the failed/interrupted step (re-run it)
                start_idx = step_order.index(current_step)
                print(f'[DEBUG] Resuming analysis {analysis.id} from step: {current_step}')
            except ValueError:
                start_idx = 0

        analysis.status = ResumeAnalysis.STATUS_PROCESSING
        analysis.error_message = ''
        analysis.save(update_fields=['status', 'error_message'])

        for step_name, method_name in self._STEPS[start_idx:]:
            print(f'[DEBUG] ── Step: {step_name} ──')
            step_start = time.time()

            # Update pipeline_step BEFORE running (so if it crashes, we know where)
            analysis.pipeline_step = step_name
            analysis.save(update_fields=['pipeline_step'])

            method = getattr(self, method_name)
            method(analysis)

            print(f'[DEBUG] ✅ {step_name} done ({time.time() - step_start:.2f}s)')

        # Mark as complete
        analysis.pipeline_step = ResumeAnalysis.STEP_DONE
        analysis.status = ResumeAnalysis.STATUS_DONE
        analysis.save(update_fields=['pipeline_step', 'status'])

        print(f'[DEBUG] ✅ PIPELINE COMPLETE — total time: {time.time() - pipeline_start:.2f}s')
        return analysis

    # ── Step 1: PDF extraction ─────────────────────────────────────────────

    def _step_pdf_extract(self, analysis: ResumeAnalysis):
        if analysis.resume_text:
            print(f'[DEBUG]   Skipping PDF extract — already have {len(analysis.resume_text)} chars')
            return

        print(f'[DEBUG]   Extracting text from PDF: {analysis.resume_file.name}')
        resume_text = self.pdf_extractor.extract(analysis.resume_file)
        analysis.resume_text = resume_text
        analysis.save(update_fields=['resume_text'])
        print(f'[DEBUG]   Extracted {len(resume_text)} chars')

    # ── Step 2: JD resolution ──────────────────────────────────────────────

    def _step_jd_scrape(self, analysis: ResumeAnalysis):
        if analysis.resolved_jd:
            print(f'[DEBUG]   Skipping JD resolve — already have {len(analysis.resolved_jd)} chars')
            return

        print(f'[DEBUG]   Resolving JD (type={analysis.jd_input_type})')
        resolved_jd, scrape_result = self._resolve_jd(analysis)
        analysis.resolved_jd = resolved_jd
        if scrape_result:
            analysis.scrape_result = scrape_result
        analysis.save(update_fields=['resolved_jd', 'scrape_result'])
        print(f'[DEBUG]   Resolved JD: {len(resolved_jd)} chars')

    # ── Step 3: LLM call ───────────────────────────────────────────────────

    def _step_llm_call(self, analysis: ResumeAnalysis):
        # If we already have a successful LLM response, skip
        if analysis.llm_response and analysis.llm_response.status == LLMResponse.STATUS_DONE:
            print(f'[DEBUG]   Skipping LLM call — already have response (id={analysis.llm_response.id})')
            return

        print(f'[DEBUG]   Sending to AI provider ({type(self.ai_provider).__name__})...')
        print(f'[DEBUG]   Resume text: {len(analysis.resume_text)} chars | JD text: {len(analysis.resolved_jd)} chars')

        # Create pending LLMResponse
        llm_resp = LLMResponse.objects.create(
            user=analysis.user,
            model_used=type(self.ai_provider).__name__,
            status=LLMResponse.STATUS_PENDING,
        )
        analysis.llm_response = llm_resp
        analysis.save(update_fields=['llm_response'])

        try:
            result = self.ai_provider.analyze(analysis.resume_text, analysis.resolved_jd)
        except ValueError as exc:
            llm_resp.status = LLMResponse.STATUS_FAILED
            llm_resp.error_message = str(exc)
            llm_resp.save(update_fields=['status', 'error_message'])
            raise

        # Persist raw + prompt + parsed atomically
        llm_resp.prompt_sent = result.get('prompt', '')
        llm_resp.raw_response = result.get('raw', '')
        llm_resp.parsed_response = result.get('parsed')
        llm_resp.model_used = result.get('model', type(self.ai_provider).__name__)
        llm_resp.duration_seconds = result.get('duration')
        llm_resp.status = LLMResponse.STATUS_DONE
        llm_resp.save(update_fields=[
            'prompt_sent', 'raw_response', 'parsed_response',
            'model_used', 'duration_seconds', 'status',
        ])
        print(f'[DEBUG]   LLMResponse saved (id={llm_resp.id})')

    # ── Step 4: Parse & persist results ────────────────────────────────────

    def _step_parse_result(self, analysis: ResumeAnalysis):
        llm_resp = analysis.llm_response
        if not llm_resp or not llm_resp.parsed_response:
            raise ValueError('No parsed LLM response available to extract results from.')

        data = llm_resp.parsed_response
        print(f'[DEBUG]   Writing analysis results — ATS={data.get("ats_score")}')

        analysis.ats_score = data.get('ats_score')
        analysis.ats_score_breakdown = data.get('ats_score_breakdown')
        analysis.keyword_gaps = data.get('keyword_gaps')
        analysis.section_suggestions = data.get('section_suggestions')
        analysis.rewritten_bullets = data.get('rewritten_bullets')
        analysis.overall_assessment = data.get('overall_assessment', '')
        analysis.ai_provider_used = llm_resp.model_used
        analysis.save(update_fields=[
            'ats_score', 'ats_score_breakdown', 'keyword_gaps',
            'section_suggestions', 'rewritten_bullets', 'overall_assessment',
            'ai_provider_used',
        ])
        print(f'[DEBUG]   ✅ Results saved (ATS={analysis.ats_score})')

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_jd(self, analysis: ResumeAnalysis) -> tuple:
        """Returns (resolved_text, scrape_result_or_None)."""
        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_TEXT:
            return analysis.jd_text, None

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_URL:
            return self.jd_fetcher.fetch(analysis.jd_url, user=analysis.user)

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_FORM:
            text = self.jd_fetcher.build_from_form(
                role=analysis.jd_role,
                company=analysis.jd_company,
                skills=analysis.jd_skills,
                experience_years=analysis.jd_experience_years,
                industry=analysis.jd_industry,
                extra_details=analysis.jd_extra_details,
            )
            return text, None

        raise ValueError(f'Unknown jd_input_type: {analysis.jd_input_type}')
