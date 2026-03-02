"""
Embedding-based job matching service (Phase 12).

Replaces LLM-based batch scoring from job_matcher.py with pgvector
cosine similarity. One fast SQL query per alert instead of one LLM
call per 15-job batch.

Includes a feedback learning loop: past user feedback (with reasons)
adjusts relevance scores via company boosting and keyword-based
penalty/boost heuristics.

Fallback: If pgvector is not available (SQLite dev), falls back to
the original LLM-based matching via job_matcher.py.
"""
import logging
import re

from django.conf import settings
from django.db.models import F

logger = logging.getLogger('analyzer')

# Minimum cosine similarity to create a JobMatch record
DEFAULT_MATCH_THRESHOLD = 0.60


def match_jobs_for_alert(job_alert, since_dt=None, job_ids=None) -> list:
    """
    Find matching jobs for a JobAlert using pgvector cosine similarity,
    then apply feedback-based adjustments.

    Args:
        job_alert: JobAlert instance with related resume and JobSearchProfile.
        since_dt: Only consider DiscoveredJob records created after this datetime.
                  If None, uses alert.last_run_at.
        job_ids: Optional list of specific DiscoveredJob IDs to score.

    Returns:
        List of dicts: [{ discovered_job_id, score, reason }]
        Only includes jobs scoring >= threshold.
    """
    from analyzer.models import DiscoveredJob, JobSearchProfile

    # Get resume's embedding from JobSearchProfile
    resume = job_alert.resume
    try:
        profile = resume.job_search_profile
    except JobSearchProfile.DoesNotExist:
        logger.warning('No JobSearchProfile for resume %s — skipping matching', resume.id)
        return []

    # Check if pgvector embeddings are available
    if not hasattr(profile, 'embedding') or profile.embedding is None:
        logger.warning(
            'No embedding on JobSearchProfile for resume %s — cannot match (no LLM fallback)',
            resume.id,
        )
        return []

    threshold = getattr(settings, 'JOB_MATCH_THRESHOLD', DEFAULT_MATCH_THRESHOLD)

    # Build queryset of candidate jobs
    qs = DiscoveredJob.objects.exclude(embedding__isnull=True)
    if job_ids:
        qs = qs.filter(id__in=job_ids)
    elif since_dt:
        qs = qs.filter(created_at__gte=since_dt)
    elif job_alert.last_run_at:
        qs = qs.filter(created_at__gte=job_alert.last_run_at)

    if not qs.exists():
        logger.info('No candidate jobs for alert %s', job_alert.id)
        return []

    # Load feedback context for the learning loop
    feedback_ctx = _build_feedback_context(job_alert)

    # pgvector cosine similarity query
    try:
        from pgvector.django import CosineDistance

        resume_embedding = profile.embedding

        # Use a slightly lower threshold to allow feedback boost to rescue borderline jobs
        query_threshold = max(threshold - 0.10, 0.40)

        # Annotate with cosine distance, filter by threshold, order by similarity
        results = (
            qs
            .annotate(distance=CosineDistance('embedding', resume_embedding))
            .filter(distance__lte=(1.0 - query_threshold))
            .order_by('distance')[:100]  # Wider net, then apply feedback adjustments
            .values('id', 'title', 'company', 'distance')
        )

        matches = []
        for row in results:
            similarity = round(1.0 - row['distance'], 4)
            base_score = int(similarity * 100)

            # Apply feedback-based adjustment
            adjusted_score = _apply_feedback_adjustments(
                base_score, row['title'], row['company'], feedback_ctx,
            )

            if adjusted_score < int(threshold * 100):
                continue

            reason = _generate_match_reason(
                adjusted_score, row['title'], row['company'], profile, feedback_ctx,
            )
            matches.append({
                'discovered_job_id': str(row['id']),
                'score': min(adjusted_score, 100),
                'reason': reason,
            })

        # Re-sort by adjusted score
        matches.sort(key=lambda m: m['score'], reverse=True)
        matches = matches[:50]  # Cap at 50

        logger.info(
            'Embedding matching: alert=%s candidates=%d matches=%d threshold=%.2f',
            job_alert.id, qs.count(), len(matches), threshold,
        )
        return matches

    except ImportError:
        logger.warning('pgvector not available — embedding matching disabled')
        return []
    except Exception as exc:
        logger.exception('Embedding matching failed for alert %s: %s', job_alert.id, exc)
        return []


# ── Feedback learning loop ────────────────────────────────────────────────────


def _build_feedback_context(job_alert) -> dict:
    """
    Build context from past user feedback on this alert.

    Returns dict with:
        - priority_companies: set of company names from alert preferences
        - excluded_companies: set of company names to exclude
        - positive_companies: set of companies from 'relevant'/'applied' feedback
        - negative_companies: set of companies from 'irrelevant'/'dismissed' feedback
        - positive_keywords: set of words from positive feedback reasons
        - negative_keywords: set of words from negative feedback reasons
    """
    from analyzer.models import JobMatch

    prefs = job_alert.preferences or {}
    ctx = {
        'priority_companies': {
            c.lower().strip() for c in prefs.get('priority_companies', []) if c
        },
        'excluded_companies': {
            c.lower().strip() for c in prefs.get('excluded_companies', []) if c
        },
        'positive_companies': set(),
        'negative_companies': set(),
        'positive_keywords': set(),
        'negative_keywords': set(),
    }

    # Load past feedback with reasons (last 200 for performance)
    past_feedback = (
        JobMatch.objects
        .filter(job_alert=job_alert)
        .exclude(user_feedback='pending')
        .select_related('discovered_job')
        .order_by('-created_at')[:200]
        .values(
            'user_feedback', 'feedback_reason',
            'discovered_job__company', 'discovered_job__title',
        )
    )

    for fb in past_feedback:
        company = (fb.get('discovered_job__company') or '').lower().strip()
        feedback = fb['user_feedback']
        reason = (fb.get('feedback_reason') or '').strip()

        if feedback in ('relevant', 'applied'):
            if company:
                ctx['positive_companies'].add(company)
            if reason:
                ctx['positive_keywords'].update(_extract_keywords(reason))
        elif feedback in ('irrelevant', 'dismissed'):
            if company:
                ctx['negative_companies'].add(company)
            if reason:
                ctx['negative_keywords'].update(_extract_keywords(reason))

    return ctx


def _extract_keywords(text: str) -> set:
    """Extract meaningful keywords from feedback reason text."""
    if not text:
        return set()
    # Remove common stop words and short words
    stop_words = {
        'the', 'a', 'an', 'is', 'was', 'are', 'were', 'be', 'been',
        'not', 'no', 'too', 'very', 'just', 'but', 'and', 'or', 'for',
        'this', 'that', 'with', 'from', 'they', 'it', 'its', 'i', 'my',
        'me', 'we', 'our', 'you', 'your', 'he', 'she', 'his', 'her',
        'of', 'in', 'on', 'at', 'to', 'by', 'as', 'so', 'if', 'do',
        'did', 'does', 'has', 'have', 'had', 'will', 'can', 'would',
        'could', 'should', 'about', 'into', 'than', 'then', 'also',
        'like', 'really', 'because', 'job', 'role', 'position', 'company',
    }
    words = re.findall(r'[a-z]+', text.lower())
    return {w for w in words if len(w) > 2 and w not in stop_words}


def _apply_feedback_adjustments(
    base_score: int,
    title: str,
    company: str,
    feedback_ctx: dict,
) -> int:
    """
    Adjust base similarity score using feedback context.

    Adjustments:
    - +10 for priority companies
    - -100 for excluded companies (effectively filters them out)
    - +5 for companies user previously marked as relevant
    - -8 for companies user previously marked as irrelevant
    - +3/-3 for keyword matches in title against positive/negative keywords
    """
    score = base_score
    company_lower = company.lower().strip() if company else ''
    title_lower = title.lower().strip() if title else ''

    # Excluded companies — hard filter
    if company_lower and company_lower in feedback_ctx['excluded_companies']:
        return 0

    # Priority companies — significant boost
    if company_lower and company_lower in feedback_ctx['priority_companies']:
        score += 10

    # Companies from past positive feedback
    if company_lower and company_lower in feedback_ctx['positive_companies']:
        score += 5

    # Companies from past negative feedback
    if company_lower and company_lower in feedback_ctx['negative_companies']:
        score -= 8

    # Keyword matching against title
    title_words = set(re.findall(r'[a-z]+', title_lower))
    positive_hits = title_words & feedback_ctx['positive_keywords']
    negative_hits = title_words & feedback_ctx['negative_keywords']

    score += len(positive_hits) * 3
    score -= len(negative_hits) * 3

    return max(score, 0)


def _generate_match_reason(
    score: int,
    title: str,
    company: str,
    profile,
    feedback_ctx: dict = None,
) -> str:
    """Generate a human-readable match reason based on similarity score and profile."""
    titles = profile.titles or []
    skills = profile.skills or []

    # Add feedback-based context to the reason
    feedback_note = ''
    if feedback_ctx:
        company_lower = (company or '').lower().strip()
        if company_lower in (feedback_ctx.get('priority_companies') or set()):
            feedback_note = ' (priority company)'
        elif company_lower in (feedback_ctx.get('positive_companies') or set()):
            feedback_note = ' (previously relevant)'

    if score >= 90:
        return f'Excellent match for "{title}" at {company}{feedback_note} — closely aligned with your target roles and skills.'
    elif score >= 75:
        return f'Strong match: "{title}" at {company}{feedback_note} aligns well with your experience in {", ".join(skills[:3])}.'
    elif score >= 60:
        matching_titles = [t for t in titles if any(
            word.lower() in title.lower() for word in t.split()
        )]
        if matching_titles:
            return f'Good match: "{title}" at {company}{feedback_note} relates to your target role "{matching_titles[0]}".'
        return f'Moderate match: "{title}" at {company}{feedback_note} has overlapping requirements with your profile.'
    else:
        return f'Partial match: "{title}" at {company}{feedback_note} shares some skills with your background.'


# _fallback_llm_matching removed in Phase E — LLM-based matching deprecated.
# All matching is now via pgvector embeddings only.
