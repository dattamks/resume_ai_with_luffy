"""
Interview prep generation service.

Takes a completed ResumeAnalysis and generates tailored interview questions
based on the analysis findings (gaps, keywords, section feedback).
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

INTERVIEW_PREP_SYSTEM_PROMPT = (
    'You are an expert interview coach and career strategist. '
    'Your task is to generate likely interview questions based on a '
    'resume analysis report.\n\n'
    'Critical rules:\n'
    '- Generate questions that interviewers would ACTUALLY ask based on the resume and JD.\n'
    '- Focus on gaps identified in the analysis (missing skills, weak sections).\n'
    '- Include behavioral, technical, and situational questions.\n'
    '- Provide sample answers that are specific to the candidate\'s background.\n'
    '- Return ONLY valid JSON with no markdown, no code fences, no explanation outside the JSON.\n'
    '- Follow the output schema exactly as specified.'
)

INTERVIEW_PREP_PROMPT_TEMPLATE = """Generate interview preparation questions customized to this resume analysis.

## ANALYSIS SUMMARY:
- Target Role: {target_role}
- Target Company: {target_company}
- Overall Grade: {overall_grade}
- ATS Score: {ats_score}
- Summary: {summary}

## KEYWORD ANALYSIS:
- Matched Keywords: {matched_keywords}
- Missing Keywords: {missing_keywords}

## SECTION FEEDBACK:
{section_feedback}

## WEAK AREAS (Quick Wins):
{quick_wins}

## RESUME EXCERPT:
{resume_excerpt}

Return ONLY valid JSON following this exact schema:

{{
  "questions": [
    {{
      "category": "<one of: behavioral, technical, situational, role_specific, gap_based>",
      "question": "<the interview question>",
      "why_asked": "<brief explanation of why an interviewer would ask this, linked to analysis findings>",
      "sample_answer": "<a strong sample answer using the candidate's actual background>",
      "difficulty": "<one of: easy, medium, hard>"
    }}
  ],
  "tips": [
    "<general interview tip specific to this role and candidate's profile>"
  ]
}}

Generate 10-15 questions covering all categories. Include at least 2 gap-based questions targeting the missing keywords or weak sections. Generate 3-5 tips.
"""


def build_interview_prep_prompt(analysis) -> str:
    """Build the interview prep prompt from analysis data."""
    keyword_analysis = analysis.keyword_analysis or {}
    section_feedback = analysis.section_feedback or []
    quick_wins = analysis.quick_wins or []

    # Format section feedback
    feedback_lines = []
    for section in section_feedback:
        name = section.get('section', 'Unknown')
        score = section.get('score', 'N/A')
        fb_list = section.get('feedback', [])
        feedback_lines.append(f"- {name} (Score: {score}): {'; '.join(fb_list[:3]) if isinstance(fb_list, list) else str(fb_list)}")

    # Format quick wins
    qw_lines = []
    for qw in quick_wins:
        qw_lines.append(f"- [{qw.get('priority', 'medium')}] {qw.get('action', '')}")

    # Truncate resume text for context
    resume_excerpt = (analysis.resume_text or '')[:3000]

    prompt = INTERVIEW_PREP_PROMPT_TEMPLATE.format(
        target_role=analysis.jd_role or 'Not specified',
        target_company=analysis.jd_company or 'Not specified',
        overall_grade=analysis.overall_grade or 'N/A',
        ats_score=analysis.ats_score or 'N/A',
        summary=analysis.summary or 'No summary available.',
        matched_keywords=', '.join(keyword_analysis.get('matched_keywords', [])),
        missing_keywords=', '.join(keyword_analysis.get('missing_keywords', [])),
        section_feedback='\n'.join(feedback_lines) or 'No section feedback available.',
        quick_wins='\n'.join(qw_lines) or 'No quick wins identified.',
        resume_excerpt=resume_excerpt,
    )

    return check_prompt_length(prompt)


def call_llm_for_interview_prep(prompt: str) -> dict:
    """Call the LLM API for interview prep generation."""
    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')
    max_tokens = getattr(settings, 'AI_MAX_TOKENS', 8192)

    messages = [
        {'role': 'system', 'content': INTERVIEW_PREP_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt},
    ]

    logger.info('Interview prep: sending LLM request — model=%s', model)
    req_start = time.time()

    @llm_retry
    def _do_call():
        return client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
            timeout=120,
        )

    response = _do_call()
    elapsed = time.time() - req_start
    logger.info('Interview prep: response received in %.2fs', elapsed)

    raw = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else None
    if not raw:
        raise ValueError('LLM returned an empty response for interview prep.')

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
            raise ValueError('Failed to parse interview prep response as JSON.')

    # Validate structure
    if 'questions' not in data or not isinstance(data['questions'], list):
        raise ValueError('Interview prep response missing "questions" array.')

    return {
        'parsed': data,
        'raw': raw,
        'prompt': json.dumps(messages),
        'model': model,
        'duration': elapsed,
        'usage': usage,
    }
