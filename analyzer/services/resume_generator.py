"""
Resume generation service.

Takes a completed ResumeAnalysis and produces an improved resume by:
1. Building a targeted rewrite prompt from analysis findings
2. Calling the LLM to rewrite the resume as structured JSON
3. Validating the output schema
4. Rendering to PDF or DOCX via template renderers

The rewrite is NOT generic — it uses the specific analysis report
(missing keywords, sentence suggestions, section feedback, quick wins)
as an improvement specification.
"""
import json
import logging
import re
import time

from django.conf import settings
from openai import OpenAI

from .ai_providers.json_repair import repair_json

logger = logging.getLogger('analyzer')

# Strip markdown code fences
_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

# ── System prompt ────────────────────────────────────────────────────────

RESUME_REWRITE_SYSTEM_PROMPT = (
    'You are a professional resume writer and ATS optimization specialist. '
    'Your task is to rewrite a candidate\'s resume incorporating specific improvements '
    'from an analysis report.\n\n'
    'Critical rules:\n'
    '- DO NOT fabricate experience, degrees, certifications, or skills the candidate does not have.\n'
    '- Only restructure, rephrase, and enhance what already exists in the resume.\n'
    '- Integrate missing keywords NATURALLY — do not keyword-stuff.\n'
    '- Use strong action verbs and quantify achievements where the original provides numbers.\n'
    '- Keep the resume concise: 1 page for <5 years experience, 1-2 pages for 5-10 years, max 2 pages for 10+ years.\n'
    '- Ensure ATS compatibility: single-column layout, standard section headings, no tables or graphics.\n'
    '- Return ONLY valid JSON with no markdown, no code fences, no explanation outside the JSON.\n'
    '- Follow the output schema exactly as specified.'
)

# ── User prompt template ─────────────────────────────────────────────────

RESUME_REWRITE_PROMPT_TEMPLATE = """Rewrite the resume below incorporating ALL the improvements identified in the analysis report.

## ORIGINAL RESUME TEXT:
{resume_text}

## TARGET ROLE CONTEXT:
- Target Role: {target_role}
- Target Company: {target_company}
- Required Skills: {target_skills}
- Industry: {target_industry}
- Experience Required: {experience_years}

## IMPROVEMENTS TO APPLY:

### Missing Keywords to Integrate:
{missing_keywords}

### Sentence Rewrites (apply these EXACT improvements):
{sentence_suggestions}

### Section-Level Feedback (improve sections scoring below 70):
{section_feedback}

### Quick Wins to Apply:
{quick_wins}

### Formatting Issues to Fix:
{formatting_flags}

## OUTPUT INSTRUCTIONS:
Return ONLY valid JSON following this exact schema. Extract ALL information from the original resume and restructure/enhance it:

{{
  "contact": {{
    "name": "<full name>",
    "email": "<email address or empty string>",
    "phone": "<phone number or empty string>",
    "location": "<city, state/country or empty string>",
    "linkedin": "<LinkedIn URL or empty string>",
    "portfolio": "<portfolio/website URL or empty string>"
  }},
  "summary": "<3-4 sentence professional summary tailored to the target role, incorporating key skills and quantified achievements>",
  "experience": [
    {{
      "title": "<job title>",
      "company": "<company name>",
      "location": "<location or empty string>",
      "start_date": "<start date as stated in resume>",
      "end_date": "<end date or 'Present'>",
      "bullets": [
        "<achievement-oriented bullet point with action verb and quantified impact where possible>"
      ]
    }}
  ],
  "education": [
    {{
      "degree": "<degree name>",
      "institution": "<institution name>",
      "location": "<location or empty string>",
      "year": "<graduation year or date range>",
      "gpa": "<GPA or empty string, only include if mentioned in original resume>"
    }}
  ],
  "skills": {{
    "technical": ["<list of technical skills, tools, technologies>"],
    "tools": ["<list of software tools, platforms>"],
    "soft": ["<list of soft skills>"]
  }},
  "certifications": [
    {{
      "name": "<certification name>",
      "issuer": "<issuing organization>",
      "year": "<year obtained or empty string>"
    }}
  ],
  "projects": [
    {{
      "name": "<project name>",
      "description": "<1-2 sentence description with impact>",
      "technologies": ["<technologies used>"],
      "url": "<project URL or empty string>"
    }}
  ]
}}

Rules:
- Include ALL sections present in the original resume
- If a section (certifications, projects) is empty in the original, return an empty array []
- experience.bullets: rewrite weak bullets using the sentence suggestions provided, use strong action verbs, quantify impact
- skills: reorganize and add the missing keywords naturally
- summary: write a new professional summary tailored to the target role
- Preserve ALL factual information — dates, company names, degrees, institutions
- Return ONLY the JSON object, nothing else
"""


def build_rewrite_prompt(analysis) -> str:
    """
    Assemble the rewrite prompt from analysis findings.

    Pulls specific improvements from the analysis report to give
    the LLM a deterministic, traceable improvement spec.
    """
    # Missing keywords
    kw_analysis = analysis.keyword_analysis or {}
    missing_kw = kw_analysis.get('missing_keywords', [])
    recommended = kw_analysis.get('recommended_to_add', [])
    missing_keywords_text = '\n'.join(
        [f'- {kw}' for kw in missing_kw]
    ) if missing_kw else '(none identified)'
    if recommended:
        missing_keywords_text += '\n\nRecommended placements:\n' + '\n'.join(
            [f'- {r}' for r in recommended]
        )

    # Sentence suggestions
    suggestions = analysis.sentence_suggestions or []
    if suggestions:
        sentence_text = '\n'.join([
            f'- Original: "{s.get("original", "")}"\n'
            f'  Suggested: "{s.get("suggested", "")}"\n'
            f'  Reason: {s.get("reason", "")}'
            for s in suggestions
        ])
    else:
        sentence_text = '(none identified)'

    # Section feedback (only sections scoring below 70)
    sections = analysis.section_feedback or []
    weak_sections = [s for s in sections if isinstance(s.get('score'), (int, float)) and s['score'] < 70]
    if weak_sections:
        section_text = '\n'.join([
            f'- {s.get("section_name", "Unknown")} (score: {s.get("score", "?")}): '
            + '; '.join(s.get('feedback', []))
            for s in weak_sections
        ])
    else:
        section_text = '(all sections scored 70+)'

    # Quick wins
    wins = analysis.quick_wins or []
    if wins:
        wins_text = '\n'.join([
            f'- Priority {w.get("priority", "?")}: {w.get("action", "")}'
            for w in wins
        ])
    else:
        wins_text = '(none identified)'

    # Formatting flags
    flags = analysis.formatting_flags or []
    flags_text = '\n'.join([f'- {f}' for f in flags]) if flags else '(none identified)'

    return RESUME_REWRITE_PROMPT_TEMPLATE.format(
        resume_text=analysis.resume_text or '(resume text not available)',
        target_role=analysis.jd_role or 'Not specified',
        target_company=analysis.jd_company or 'Not specified',
        target_skills=analysis.jd_skills or 'Not specified',
        target_industry=analysis.jd_industry or 'Not specified',
        experience_years=f'{analysis.jd_experience_years} years' if analysis.jd_experience_years else 'Not specified',
        missing_keywords=missing_keywords_text,
        sentence_suggestions=sentence_text,
        section_feedback=section_text,
        quick_wins=wins_text,
        formatting_flags=flags_text,
    )


# ── Schema validation ────────────────────────────────────────────────────

_REQUIRED_TOP_LEVEL = {
    'contact': dict,
    'summary': str,
    'experience': list,
    'education': list,
    'skills': dict,
}

_REQUIRED_CONTACT_FIELDS = {'name'}


def validate_resume_output(data: dict) -> dict:
    """
    Validate the LLM resume output against the expected schema.
    Fills in missing optional fields with defaults.
    Raises ValueError on critical schema violations.
    Returns the cleaned/normalized data.
    """
    # Top-level fields
    for field, expected_type in _REQUIRED_TOP_LEVEL.items():
        if field not in data:
            raise ValueError(f'Resume output missing required field: "{field}"')
        if not isinstance(data[field], expected_type):
            raise ValueError(
                f'Resume output field "{field}" expected {expected_type.__name__}, '
                f'got {type(data[field]).__name__}'
            )

    # Contact validation
    contact = data['contact']
    if 'name' not in contact or not contact['name'].strip():
        raise ValueError('Resume output "contact.name" is required and cannot be empty')

    # Fill optional contact fields
    for key in ('email', 'phone', 'location', 'linkedin', 'portfolio'):
        contact.setdefault(key, '')

    # Validate experience entries
    for i, exp in enumerate(data['experience']):
        if not isinstance(exp, dict):
            raise ValueError(f'Resume output "experience[{i}]" must be a dict')
        for key in ('title', 'company'):
            if key not in exp or not exp[key]:
                raise ValueError(f'Resume output "experience[{i}].{key}" is required')
        exp.setdefault('location', '')
        exp.setdefault('start_date', '')
        exp.setdefault('end_date', '')
        exp.setdefault('bullets', [])

    # Validate education entries
    for i, edu in enumerate(data['education']):
        if not isinstance(edu, dict):
            raise ValueError(f'Resume output "education[{i}]" must be a dict')
        edu.setdefault('degree', '')
        edu.setdefault('institution', '')
        edu.setdefault('location', '')
        edu.setdefault('year', '')
        edu.setdefault('gpa', '')

    # Validate skills
    skills = data['skills']
    skills.setdefault('technical', [])
    skills.setdefault('tools', [])
    skills.setdefault('soft', [])

    # Optional arrays
    data.setdefault('certifications', [])
    data.setdefault('projects', [])

    # Validate certifications
    for i, cert in enumerate(data.get('certifications', [])):
        if not isinstance(cert, dict):
            raise ValueError(f'Resume output "certifications[{i}]" must be a dict')
        cert.setdefault('name', '')
        cert.setdefault('issuer', '')
        cert.setdefault('year', '')

    # Validate projects
    for i, proj in enumerate(data.get('projects', [])):
        if not isinstance(proj, dict):
            raise ValueError(f'Resume output "projects[{i}]" must be a dict')
        proj.setdefault('name', '')
        proj.setdefault('description', '')
        proj.setdefault('technologies', [])
        proj.setdefault('url', '')

    return data


# ── LLM call ─────────────────────────────────────────────────────────────

def call_llm_for_rewrite(analysis) -> dict:
    """
    Call the LLM to rewrite the resume based on analysis findings.

    Returns dict with keys: parsed, raw, prompt, model, duration.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    if not api_key:
        raise ValueError('OPENROUTER_API_KEY not configured')

    client = OpenAI(api_key=api_key, base_url=base_url)

    user_prompt = build_rewrite_prompt(analysis)
    max_tokens = getattr(settings, 'AI_MAX_TOKENS', 4096)

    messages = [
        {'role': 'system', 'content': RESUME_REWRITE_SYSTEM_PROMPT},
        {'role': 'user', 'content': user_prompt},
    ]

    logger.info('Resume rewrite LLM call: analysis_id=%s model=%s', analysis.id, model)
    req_start = time.time()

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
        timeout=120,
    )

    elapsed = time.time() - req_start
    logger.info('Resume rewrite LLM response in %.2fs: analysis_id=%s', elapsed, analysis.id)

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning('Resume rewrite returned non-JSON, attempting repair...')
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            logger.error('Resume rewrite JSON repair failed: %s', raw[:500])
            raise ValueError('LLM returned non-JSON response for resume rewrite and repair failed.')

    # Validate and clean
    data = validate_resume_output(data)

    return {
        'parsed': data,
        'raw': raw,
        'prompt': json.dumps(messages),
        'model': model,
        'duration': elapsed,
    }
