"""
Cover letter generation service.

Takes a completed ResumeAnalysis and generates a tailored cover letter
using the analysis findings (matched keywords, resume content, JD context).
"""
import json
import logging
import re
import time

from django.conf import settings

from .ai_providers.factory import get_openai_client, llm_retry
from .ai_providers.base import check_prompt_length
from .ai_providers.json_repair import repair_json

logger = logging.getLogger('analyzer')

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

COVER_LETTER_SYSTEM_PROMPT = (
    'You are a professional career coach and cover letter specialist. '
    'Your task is to write a compelling, personalized cover letter based on '
    'a resume analysis report.\n\n'
    'Critical rules:\n'
    '- DO NOT fabricate experience, skills, or achievements not present in the resume.\n'
    '- Tailor the letter specifically to the target role and company.\n'
    '- Highlight the candidate\'s strongest matches to the JD requirements.\n'
    '- Address skill gaps positively — frame as eagerness to learn, transferable skills, etc.\n'
    '- Keep it concise: 3-4 paragraphs, 250-400 words.\n'
    '- Use the specified tone throughout.\n'
    '- Return ONLY valid JSON with no markdown, no code fences, no explanation outside the JSON.\n'
    '- Follow the output schema exactly as specified.'
)

COVER_LETTER_PROMPT_TEMPLATE = """Write a cover letter based on the following resume analysis.

## TARGET ROLE CONTEXT:
- Target Role: {target_role}
- Target Company: {target_company}
- Industry: {industry}

## ANALYSIS FINDINGS:
- Overall Grade: {overall_grade}
- ATS Score: {ats_score}
- Matched Keywords: {matched_keywords}
- Missing Keywords: {missing_keywords}
- Summary: {summary}

## KEY STRENGTHS (from section feedback):
{strengths}

## RESUME EXCERPT:
{resume_excerpt}

## TONE: {tone}

Return ONLY valid JSON following this exact schema:

{{
  "subject_line": "<suggested email subject line for the cover letter>",
  "greeting": "<appropriate greeting, e.g., 'Dear Hiring Manager,' or 'Dear [Company] Team,'>",
  "paragraphs": [
    "<opening paragraph — hook + role you're applying for>",
    "<body paragraph(s) — key qualifications matched to JD requirements>",
    "<closing paragraph — call to action + availability>"
  ],
  "sign_off": "<e.g., 'Sincerely,' or 'Best regards,'>",
  "full_text": "<the complete cover letter as a single formatted text>",
  "full_html": "<the complete cover letter as HTML with proper paragraphs>"
}}

Write a {tone} cover letter that is 250-400 words. The full_text should be ready to copy-paste. The full_html should have proper <p> tags for each paragraph.
"""


def build_cover_letter_prompt(analysis, tone='professional') -> str:
    """Build the cover letter prompt from analysis data."""
    keyword_analysis = analysis.keyword_analysis or {}
    section_feedback = analysis.section_feedback or []

    # Extract strengths from high-scoring sections
    strengths = []
    for section in section_feedback:
        score = section.get('score', 0)
        if isinstance(score, (int, float)) and score >= 70:
            name = section.get('section', 'Unknown')
            fb_list = section.get('feedback', [])
            strengths.append(f"- {name} (Score: {score})")

    resume_excerpt = (analysis.resume_text or '')[:3000]

    prompt = COVER_LETTER_PROMPT_TEMPLATE.format(
        target_role=analysis.jd_role or 'Not specified',
        target_company=analysis.jd_company or 'Not specified',
        industry=analysis.jd_industry or 'Not specified',
        overall_grade=analysis.overall_grade or 'N/A',
        ats_score=analysis.ats_score or 'N/A',
        matched_keywords=', '.join(keyword_analysis.get('matched_keywords', [])),
        missing_keywords=', '.join(keyword_analysis.get('missing_keywords', [])),
        summary=analysis.summary or 'No summary available.',
        strengths='\n'.join(strengths) or 'No specific strengths highlighted.',
        resume_excerpt=resume_excerpt,
        tone=tone,
    )

    return check_prompt_length(prompt)


def call_llm_for_cover_letter(prompt: str) -> dict:
    """Call the LLM API for cover letter generation."""
    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')
    max_tokens = getattr(settings, 'AI_MAX_TOKENS', 8192)

    messages = [
        {'role': 'system', 'content': COVER_LETTER_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt},
    ]

    logger.info('Cover letter: sending LLM request — model=%s', model)
    req_start = time.time()

    @llm_retry
    def _do_call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.5,
            timeout=120,
        )

    response = _do_call()
    elapsed = time.time() - req_start
    logger.info('Cover letter: response received in %.2fs', elapsed)

    raw = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None
    if not raw:
        raise ValueError('LLM returned an empty response for cover letter.')

    # Extract token usage
    usage = {}
    if hasattr(response, 'usage') and response.usage:
        usage = {
            'prompt_tokens': getattr(response.usage, 'prompt_tokens', None),
            'completion_tokens': getattr(response.usage, 'completion_tokens', None),
            'total_tokens': getattr(response.usage, 'total_tokens', None),
        }

    # Strip markdown fences
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    # Parse JSON
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise ValueError('Failed to parse cover letter response as JSON.')

    # Validate structure
    if 'full_text' not in data:
        raise ValueError('Cover letter response missing "full_text".')

    return {
        'parsed': data,
        'raw': raw,
        'prompt': json.dumps(messages),
        'model': model,
        'duration': elapsed,
        'usage': usage,
    }
