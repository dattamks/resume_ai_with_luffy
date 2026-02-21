from ..models import ResumeAnalysis
from .pdf_extractor import PDFExtractor
from .jd_fetcher import JDFetcher
from .ai_providers.factory import get_ai_provider


class ResumeAnalyzer:
    """
    Orchestrates the full resume analysis pipeline:
    1. Extract text from the uploaded PDF
    2. Resolve the job description (text / URL scrape / form assembly)
    3. Call the configured AI provider
    4. Persist and return the updated ResumeAnalysis instance
    """

    def __init__(self):
        self.pdf_extractor = PDFExtractor()
        self.jd_fetcher = JDFetcher()
        self.ai_provider = get_ai_provider()

    def run(self, analysis: ResumeAnalysis) -> ResumeAnalysis:
        # Step 1: Extract resume text
        resume_text = self.pdf_extractor.extract(analysis.resume_file.path)
        analysis.resume_text = resume_text

        # Step 2: Resolve job description
        resolved_jd = self._resolve_jd(analysis)
        analysis.resolved_jd = resolved_jd

        # Step 3: AI analysis
        result = self.ai_provider.analyze(resume_text, resolved_jd)

        # Step 4: Persist results
        analysis.ats_score = result.get('ats_score')
        analysis.ats_score_breakdown = result.get('ats_score_breakdown')
        analysis.keyword_gaps = result.get('keyword_gaps')
        analysis.section_suggestions = result.get('section_suggestions')
        analysis.rewritten_bullets = result.get('rewritten_bullets')
        analysis.overall_assessment = result.get('overall_assessment', '')
        analysis.ai_provider_used = type(self.ai_provider).__name__
        analysis.status = ResumeAnalysis.STATUS_DONE

        analysis.save()
        return analysis

    def _resolve_jd(self, analysis: ResumeAnalysis) -> str:
        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_TEXT:
            return analysis.jd_text

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_URL:
            return self.jd_fetcher.fetch(analysis.jd_url)

        if analysis.jd_input_type == ResumeAnalysis.JD_INPUT_FORM:
            return self.jd_fetcher.build_from_form(
                role=analysis.jd_role,
                company=analysis.jd_company,
                skills=analysis.jd_skills,
                experience_years=analysis.jd_experience_years,
                industry=analysis.jd_industry,
                extra_details=analysis.jd_extra_details,
            )

        raise ValueError(f'Unknown jd_input_type: {analysis.jd_input_type}')
