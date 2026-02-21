from abc import ABC, abstractmethod


ANALYSIS_PROMPT_TEMPLATE = """You are an expert resume reviewer and ATS (Applicant Tracking System) optimization specialist.

Analyze the resume below against the provided job description and return a structured evaluation.

---
RESUME:
{resume_text}

---
JOB DESCRIPTION:
{job_description}

---
Return ONLY valid JSON — no markdown, no explanation, no extra text. Use this exact schema:

{{
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
            Parsed dict matching the schema in ANALYSIS_PROMPT_TEMPLATE.
        """
        ...

    def _build_prompt(self, resume_text: str, job_description: str) -> str:
        return ANALYSIS_PROMPT_TEMPLATE.format(
            resume_text=resume_text,
            job_description=job_description,
        )
