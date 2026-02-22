import logging
from abc import ABC, abstractmethod

logger = logging.getLogger('analyzer')

ANALYSIS_PROMPT_TEMPLATE = """You are an expert resume reviewer and ATS (Applicant Tracking System) optimization specialist.

Analyze the resume below against the provided job description and return a structured evaluation.

---
RESUME:
{resume_text}

---
JOB DESCRIPTION:
{job_description}

---
Use this exact schema:

{{
  "job_metadata": {{
    "job_title": "<job title/role extracted from the job description>",
    "company": "<company name extracted from the job description, or empty string if not found>",
    "skills": "<comma-separated key skills/technologies required by the JD>",
    "experience_years": <integer or null — years of experience required, null if not stated>,
    "industry": "<industry or domain the role belongs to, e.g. 'FinTech', 'Healthcare', or empty string if unclear>",
    "extra_details": "<2-4 sentence summary of other important JD details: location, benefits, team size, work model, etc.>"
  }},
  "ats_score": <integer 0-100>,
  "ats_score_breakdown": {{
    "keyword_match": <integer 0-100, how many JD keywords appear in resume>,
    "format_score": <integer 0-100, resume structure and readability>,
    "relevance_score": <integer 0-100, overall alignment with the role>
  }},
  "keyword_gaps": [
    "<keyword or skill from JD missing in resume>",
    ...
  ],
  "section_suggestions": {{
    "summary": "<specific suggestion for the summary/objective section, or 'Not present — consider adding one'>",
    "experience": "<actionable feedback on work experience bullets and descriptions>",
    "skills": "<feedback on skills section — missing skills, formatting, etc.>",
    "education": "<feedback on education section>",
    "overall": "<high-level structural and content feedback>"
  }},
  "rewritten_bullets": [
    {{
      "original": "<original bullet point from resume>",
      "rewritten": "<improved, action-verb-led, metrics-driven version>",
      "reason": "<brief explanation of what was improved>"
    }}
  ],
  "overall_assessment": "<2-3 sentence summary: strengths, biggest gaps, priority actions>"
}}
"""

_REQUIRED_FIELDS = {
    'job_metadata': dict,
    'ats_score': int,
    'ats_score_breakdown': dict,
    'keyword_gaps': list,
    'section_suggestions': dict,
    'rewritten_bullets': list,
    'overall_assessment': str,
}

_REQUIRED_JOB_METADATA_FIELDS = {'job_title', 'company'}

_REQUIRED_BREAKDOWN_FIELDS = {'keyword_match', 'format_score', 'relevance_score'}
_REQUIRED_SECTION_FIELDS = {'summary', 'experience', 'skills', 'education', 'overall'}


def validate_ai_response(data: dict) -> None:
    """
    Validate that the AI response matches the expected schema.
    Raises ValueError with a descriptive message on any mismatch.
    """
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in data:
            raise ValueError(f'AI response missing required field: "{field}"')
        if not isinstance(data[field], expected_type):
            raise ValueError(
                f'AI response field "{field}" expected {expected_type.__name__}, '
                f'got {type(data[field]).__name__}'
            )

    # Validate ats_score range
    score = data['ats_score']
    if not (0 <= score <= 100):
        raise ValueError(f'AI response "ats_score" out of range [0, 100]: {score}')

    # Validate breakdown sub-fields
    breakdown = data['ats_score_breakdown']
    missing = _REQUIRED_BREAKDOWN_FIELDS - set(breakdown.keys())
    if missing:
        raise ValueError(f'AI response "ats_score_breakdown" missing fields: {missing}')
    for k in _REQUIRED_BREAKDOWN_FIELDS:
        if not isinstance(breakdown.get(k), (int, float)):
            raise ValueError(f'AI response "ats_score_breakdown.{k}" must be numeric')

    # Validate job_metadata sub-fields
    job_meta = data['job_metadata']
    missing_meta = _REQUIRED_JOB_METADATA_FIELDS - set(job_meta.keys())
    if missing_meta:
        raise ValueError(f'AI response "job_metadata" missing fields: {missing_meta}')

    # Validate section_suggestions sub-fields
    sections = data['section_suggestions']
    missing_sections = _REQUIRED_SECTION_FIELDS - set(sections.keys())
    if missing_sections:
        raise ValueError(f'AI response "section_suggestions" missing fields: {missing_sections}')


class AIProvider(ABC):
    """Abstract base for AI provider implementations."""

    @abstractmethod
    def analyze(self, resume_text: str, job_description: str) -> dict:
        """
        Run resume analysis against the job description.

        Args:
            resume_text: Plain text extracted from the resume PDF.
            job_description: Resolved job description string.

        Returns:
            Dict with keys:
              - 'parsed': Validated dict matching the analysis schema.
              - 'raw': Raw LLM text output as-is.
              - 'prompt': The prompt/messages sent to the LLM.
              - 'model': Model name used.
              - 'duration': Seconds the API call took (float).
        """
        ...

    def _build_prompt(self, resume_text: str, job_description: str) -> str:
        return ANALYSIS_PROMPT_TEMPLATE.format(
            resume_text=resume_text,
            job_description=job_description,
        )
