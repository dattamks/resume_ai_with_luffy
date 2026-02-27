"""
Job matching service.

Given a JobAlert (with its linked resume and search profile) and a list of
DiscoveredJob IDs, calls the LLM in batch to score each job's relevance
(0-100) and generate a short match reason.

Only jobs scoring ≥ MATCH_THRESHOLD are saved as JobMatch records.
"""
import json
import logging
import re
import time

from django.conf import settings

from .ai_providers.factory import get_openai_client, llm_retry
from .ai_providers.json_repair import repair_json

logger = logging.getLogger('analyzer')

_MD_FENCE_RE = re.compile(r'^```(?:json)?\s*\n?(.*?)\n?\s*```$', re.DOTALL)

# Minimum relevance score to create a JobMatch record
MATCH_THRESHOLD = 60

# ── System prompt ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    'You are a professional job recruiter. Given a candidate\'s resume summary '
    'and a list of job postings, score how relevant each job is for the candidate '
    'on a scale of 0-100. Be realistic — only score above 70 if the match is genuinely strong. '
    'Return ONLY valid JSON with no markdown, no code fences, no explanation outside the JSON. '
    'Follow the schema exactly as specified.'
)

# ── Prompt templates ──────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """Score the relevance of each job posting for the candidate below.

CANDIDATE PROFILE:
- Titles they are suited for: {titles}
- Key skills: {skills}
- Seniority: {seniority}
- Industries: {industries}
- Years of experience: {experience_years}

JOB POSTINGS (JSON array):
{jobs_json}

Return ONLY valid JSON following this exact schema:

[
  {{
    "id": "<exactly the job_id value from the input, unchanged>",
    "score": <integer 0-100 — relevance score>,
    "reason": "<1-2 sentence explanation of why this job does or does not match the candidate>"
  }}
]

Scoring guide:
- 90-100: Near-perfect match (title, skills, seniority all align)
- 70-89: Strong match (most criteria align, minor gaps)
- 50-69: Moderate match (role is related but significant gaps)
- 30-49: Weak match (adjacent field or missing key skills)
- 0-29: Poor match (wrong domain, level, or skills)

Return one entry per job in the same order as the input.
"""


def match_jobs(job_alert, discovered_jobs) -> list:
    """
    Score a list of DiscoveredJob objects for relevance to a JobAlert's resume.

    Args:
        job_alert: JobAlert instance with related resume and job_search_profile.
        discovered_jobs: Queryset or list of DiscoveredJob instances to score.

    Returns:
        List of dicts with keys: discovered_job_id, score, reason.
        Only includes jobs scoring ≥ MATCH_THRESHOLD.
    """
    jobs_list = list(discovered_jobs)
    if not jobs_list:
        return []

    # Get search profile for resume
    resume = job_alert.resume
    try:
        profile = resume.job_search_profile
    except Exception:
        logger.warning('No JobSearchProfile for resume %s — using empty profile', resume.id)
        profile = None

    titles = profile.titles if profile else []
    skills = profile.skills if profile else []
    seniority = profile.seniority if profile else 'mid'
    industries = profile.industries if profile else []
    experience_years = profile.experience_years if profile else None

    # Build jobs payload (cap at 15 per batch to keep prompt manageable)
    results = []
    batches = [jobs_list[i:i + 15] for i in range(0, len(jobs_list), 15)]

    for batch in batches:
        try:
            batch_results = _score_batch(
                batch=batch,
                titles=titles,
                skills=skills,
                seniority=seniority,
                industries=industries,
                experience_years=experience_years,
            )
            results.extend(batch_results)
        except Exception as exc:
            logger.warning(
                'Job matcher batch failed (alert=%s, batch_size=%d): %s',
                job_alert.id, len(batch), exc,
            )
            # Continue with other batches rather than failing the entire run

    logger.info(
        'Job matching: alert=%s total=%d above_threshold=%d',
        job_alert.id, len(jobs_list),
        sum(1 for r in results if r['score'] >= MATCH_THRESHOLD),
    )
    return results


def _score_batch(batch, titles, skills, seniority, industries, experience_years) -> list:
    """Score a single batch of ≤15 jobs."""
    jobs_payload = [
        {
            'job_id': str(job.id),
            'title': job.title,
            'company': job.company,
            'location': job.location,
            'description': job.description_snippet[:300],
        }
        for job in batch
    ]

    prompt = _PROMPT_TEMPLATE.format(
        titles=', '.join(titles[:3]) or 'Not specified',
        skills=', '.join(skills[:10]) or 'Not specified',
        seniority=seniority,
        industries=', '.join(industries[:3]) or 'Not specified',
        experience_years=experience_years or 'Not specified',
        jobs_json=json.dumps(jobs_payload, indent=2),
    )

    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured.')

    client = get_openai_client()
    start = time.monotonic()

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': _SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
            timeout=60,
        )

    response = _call()
    duration = time.monotonic() - start
    logger.debug('Job matching LLM call: batch_size=%d duration=%.2fs', len(batch), duration)

    raw = (response.choices[0].message.content or '').strip()

    # Strip markdown fences
    fence_match = _MD_FENCE_RE.match(raw)
    if fence_match:
        raw = fence_match.group(1).strip()

    try:
        scored = json.loads(raw)
    except json.JSONDecodeError:
        repaired = repair_json(raw)
        try:
            scored = json.loads(repaired)
        except json.JSONDecodeError as exc:
            logger.warning('Job matcher LLM returned non-JSON (raw length=%d)', len(raw))
            raise ValueError(f'LLM returned non-JSON (raw length={len(raw)})') from exc

    if not isinstance(scored, list):
        logger.warning('Job matcher LLM returned non-list: %s', type(scored))
        return []

    results = []
    for item in scored:
        if not isinstance(item, dict):
            continue
        try:
            score = max(0, min(100, int(item.get('score', 0))))
        except (TypeError, ValueError):
            score = 0
        results.append({
            'discovered_job_id': str(item.get('id', '')),
            'score': score,
            'reason': str(item.get('reason', ''))[:500],
        })

    return results
