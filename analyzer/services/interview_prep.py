"""
Interview prep generation service — Phase C rewrite.

Generates tailored interview questions from a curated DB question bank
filtered by role, skills, and gap data from analysis results.

Replaces the previous LLM-based approach with instant DB lookups.
The LLM functions are kept as legacy fallback for transitional use.
"""
import json
import logging
import re
import time

from django.conf import settings
from django.db.models import Q

logger = logging.getLogger('analyzer')


# ══════════════════════════════════════════════════════════════════════════════
# Phase C: DB-based interview prep (primary path)
# ══════════════════════════════════════════════════════════════════════════════

def generate_interview_prep_from_db(analysis) -> dict:
    """
    Generate interview prep questions from the DB question bank,
    filtered and personalized using analysis data.

    Returns:
        dict with keys: questions (list), tips (list)
    """
    from analyzer.models import InterviewQuestion

    role = (analysis.jd_role or '').lower().strip()
    company = analysis.jd_company or 'the company'
    keyword_analysis = analysis.keyword_analysis or {}
    missing_keywords = [k.lower() for k in keyword_analysis.get('missing_keywords', [])]
    matched_keywords = [k.lower() for k in keyword_analysis.get('matched_keywords', [])]
    all_keywords = set(missing_keywords + matched_keywords)
    section_feedback = analysis.section_feedback or []

    # Identify weak sections (score < 70)
    weak_sections = []
    for section in section_feedback:
        score = section.get('score')
        if score is not None and isinstance(score, (int, float)) and score < 70:
            weak_sections.append(section.get('section', '').lower())

    # Build query filters
    active_qs = InterviewQuestion.objects.filter(is_active=True)

    # 1. Role-specific questions — match role against roles JSON field
    role_questions = []
    if role:
        # Match questions where any role pattern appears in the target role
        role_words = set(role.split())
        for q in active_qs.filter(category=InterviewQuestion.CATEGORY_ROLE_SPECIFIC):
            q_roles = [r.lower() for r in (q.roles or [])]
            if any(
                any(word in role for word in r.split())
                for r in q_roles
            ) or not q_roles:
                role_questions.append(q)
                if len(role_questions) >= 3:
                    break

    # 2. Gap-based questions — match missing keywords against tags
    gap_questions = []
    if missing_keywords:
        for q in active_qs.filter(category=InterviewQuestion.CATEGORY_GAP_BASED):
            q_tags = set(t.lower() for t in (q.tags or []))
            if q_tags & set(missing_keywords):
                gap_questions.append(q)
                if len(gap_questions) >= 3:
                    break

    # 3. Technical questions — match matched keywords against tags
    tech_questions = []
    for q in active_qs.filter(category=InterviewQuestion.CATEGORY_TECHNICAL):
        q_tags = set(t.lower() for t in (q.tags or []))
        if q_tags & all_keywords or not q_tags:
            tech_questions.append(q)
            if len(tech_questions) >= 3:
                break

    # 4. Behavioral questions — always include some
    behavioral_questions = list(
        active_qs.filter(category=InterviewQuestion.CATEGORY_BEHAVIORAL)[:3]
    )

    # 5. Situational questions
    situational_questions = list(
        active_qs.filter(category=InterviewQuestion.CATEGORY_SITUATIONAL)[:2]
    )

    # Combine and deduplicate
    seen_ids = set()
    all_questions = []
    for q in (gap_questions + role_questions + tech_questions + behavioral_questions + situational_questions):
        if q.id not in seen_ids:
            seen_ids.add(q.id)
            all_questions.append(q)

    # Cap at 15 questions
    all_questions = all_questions[:15]

    # If we got too few from DB, fill with generic questions
    if len(all_questions) < 5:
        fillers = active_qs.exclude(id__in=seen_ids).order_by('?')[:max(5 - len(all_questions), 0)]
        all_questions.extend(fillers)

    # Render with context
    context = {
        'role': analysis.jd_role or 'the position',
        'company': company,
        'skill': ', '.join(missing_keywords[:3]) if missing_keywords else 'relevant skills',
    }

    rendered_questions = [q.render(context) for q in all_questions]

    # Generate tips based on analysis data
    tips = _generate_tips(analysis, weak_sections, missing_keywords)

    return {
        'questions': rendered_questions,
        'tips': tips,
    }


def _generate_tips(analysis, weak_sections, missing_keywords) -> list:
    """Generate contextual interview tips from analysis data."""
    tips = []

    role = analysis.jd_role or 'the role'
    company = analysis.jd_company or 'the company'

    # Always include a research tip
    tips.append(f'Research {company} thoroughly — understand their products, culture, and recent news.')

    # Tip based on ATS score
    if analysis.ats_score and analysis.ats_score < 70:
        tips.append(
            f'Your ATS score is {analysis.ats_score}%. Be prepared to explain how your experience '
            f'aligns with the {role} requirements, even if your resume doesn\'t highlight it well.'
        )

    # Gap-based tip
    if missing_keywords:
        skills_str = ', '.join(missing_keywords[:3])
        tips.append(
            f'The job requires {skills_str} which aren\'t prominent in your resume. '
            'Prepare examples of related experience or express eagerness to learn.'
        )

    # Weak section tip
    if weak_sections:
        tips.append(
            f'Your {", ".join(weak_sections[:2])} section(s) scored below average. '
            'Prepare strong talking points to address these areas in the interview.'
        )

    # General tips
    tips.append('Use the STAR method (Situation, Task, Action, Result) for behavioral questions.')
    tips.append(f'Prepare 2-3 thoughtful questions to ask the interviewer about {role} at {company}.')

    return tips[:5]


# ══════════════════════════════════════════════════════════════════════════════
# Legacy LLM-based functions (kept for backward compat / transitional use)
# ══════════════════════════════════════════════════════════════════════════════

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

from .ai_providers.factory import get_openai_client, llm_retry
from .ai_providers.base import check_prompt_length
from .ai_providers.json_repair import repair_json

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
    """Build the interview prep prompt from analysis data (legacy LLM path)."""
    keyword_analysis = analysis.keyword_analysis or {}
    section_feedback = analysis.section_feedback or []
    quick_wins = analysis.quick_wins or []

    feedback_lines = []
    for section in section_feedback:
        name = section.get('section', 'Unknown')
        score = section.get('score', 'N/A')
        fb_list = section.get('feedback', [])
        feedback_lines.append(f"- {name} (Score: {score}): {'; '.join(fb_list[:3]) if isinstance(fb_list, list) else str(fb_list)}")

    qw_lines = []
    for qw in quick_wins:
        qw_lines.append(f"- [{qw.get('priority', 'medium')}] {qw.get('action', '')}")

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
    """Call the LLM API for interview prep generation (legacy path)."""
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

    usage = {}
    if hasattr(response, 'usage') and response.usage:
        usage = {
            'prompt_tokens': getattr(response.usage, 'prompt_tokens', None),
            'completion_tokens': getattr(response.usage, 'completion_tokens', None),
            'total_tokens': getattr(response.usage, 'total_tokens', None),
        }

    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise ValueError('Failed to parse interview prep response as JSON.')

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
