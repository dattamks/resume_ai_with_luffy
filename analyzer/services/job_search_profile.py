"""
Job search profile extraction service.

Extracts structured job search criteria from a resume using an LLM.
The extracted profile is used to build search queries for external job APIs.

Output schema: titles, skills, seniority, industries, locations, experience_years
"""
import json
import logging
import re
import time

from django.conf import settings
from openai import OpenAI

from .ai_providers.json_repair import repair_json

logger = logging.getLogger('analyzer')

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

# ── System prompt ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    'You are an expert career analyst. Given a resume, extract the candidate\'s '
    'job search criteria: what kind of roles they are suited for, their skill set, '
    'seniority level, preferred industries, and possible work locations. '
    'Return ONLY valid JSON with no markdown, no code fences, no explanation outside the JSON. '
    'Follow the schema exactly as specified.'
)

# ── User prompt template ──────────────────────────────────────────────────

_PROMPT_TEMPLATE = """Extract job search criteria from the resume below.

RESUME TEXT:
{resume_text}

Return ONLY valid JSON following this exact schema:

{{
  "titles": ["<list of 3-5 specific job titles this candidate is best suited for, e.g. 'Senior Python Developer', 'Backend Engineer'>"],
  "skills": ["<list of the candidate's top 10-15 technical and soft skills>"],
  "seniority": "<one of: junior, mid, senior, lead, executive — inferred from years of experience and roles>",
  "industries": ["<list of 2-4 industries this candidate has experience in or is suitable for>"],
  "locations": ["<list of cities/regions mentioned in resume or inferred from education/work history, or empty list if unclear>"],
  "experience_years": <integer — total years of professional experience, or null if unclear>
}}

Rules:
- titles must be specific and searchable (suitable as job search queries)
- skills must be from the resume only — do not add skills the candidate didn't demonstrate
- seniority must be exactly one of: junior, mid, senior, lead, executive
- experience_years is the total career length, not just the last role
"""


def extract_search_profile(resume) -> dict:
    """
    Call the LLM to extract job search criteria from a resume's text.

    Args:
        resume: Resume model instance with text accessible via related analysis
                or via resume file extraction.

    Returns:
        dict with keys: titles, skills, seniority, industries, locations,
        experience_years, raw_extraction (full LLM output), duration_seconds.

    Raises:
        ValueError: If the LLM call fails or returns unparseable output.
    """
    # Get resume text — prefer the latest completed analysis, fall back to empty
    resume_text = _get_resume_text(resume)
    if not resume_text or len(resume_text.strip()) < 50:
        raise ValueError(
            f'Resume {resume.id} has no extractable text. '
            'Upload a readable PDF first.'
        )

    # Build prompt
    prompt = _PROMPT_TEMPLATE.format(resume_text=resume_text[:6000])

    # Call LLM
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured.')

    client = OpenAI(api_key=api_key, base_url=base_url)

    logger.info('Extracting job search profile for resume id=%s', resume.id)
    start = time.monotonic()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': _SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        temperature=0.2,
        max_tokens=1000,
        timeout=60,
    )
    duration = time.monotonic() - start

    raw = (response.choices[0].message.content or '').strip()

    # Strip markdown fences if present
    match = _MD_FENCE_RE.match(raw)
    if match:
        raw = match.group(1).strip()

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise ValueError(f'LLM returned non-JSON output: {raw[:200]}') from exc

    # Validate and normalise
    result = _validate_profile(data)
    result['raw_extraction'] = data
    result['duration_seconds'] = round(duration, 2)

    logger.info(
        'Job search profile extracted: resume=%s seniority=%s titles=%s (%.2fs)',
        resume.id, result.get('seniority'), result.get('titles', [])[:2], duration,
    )
    return result


def _validate_profile(data: dict) -> dict:
    """Validate and normalise the LLM output against the expected schema."""
    valid_seniority = {'junior', 'mid', 'senior', 'lead', 'executive'}

    seniority = str(data.get('seniority', '')).lower()
    if seniority not in valid_seniority:
        seniority = 'mid'

    def _ensure_list(val, default=None):
        if isinstance(val, list):
            return [str(x) for x in val if x]
        return default or []

    return {
        'titles': _ensure_list(data.get('titles'))[:5],
        'skills': _ensure_list(data.get('skills'))[:20],
        'seniority': seniority,
        'industries': _ensure_list(data.get('industries'))[:4],
        'locations': _ensure_list(data.get('locations'))[:5],
        'experience_years': int(data['experience_years']) if str(data.get('experience_years', '')).isdigit() else None,
    }


def _get_resume_text(resume) -> str:
    """
    Get the resume's text content.

    Prefers the resume_text from the latest completed ResumeAnalysis,
    since that's already been extracted and cleaned.
    """
    # Try to get from a completed analysis
    latest_analysis = (
        resume.analyses
        .filter(status='done', resume_text__gt='')
        .order_by('-created_at')
        .first()
    )
    if latest_analysis and latest_analysis.resume_text:
        return latest_analysis.resume_text

    # Fall back to PDF extraction
    from .pdf_extractor import extract_text_from_pdf
    try:
        text = extract_text_from_pdf(resume.file)
        return text or ''
    except Exception as exc:
        logger.warning('Could not extract text from resume %s: %s', resume.id, exc)
        return ''
