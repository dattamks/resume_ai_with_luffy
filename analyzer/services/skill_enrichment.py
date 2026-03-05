"""
Skill enrichment service — upserts Skill records from DiscoveredJob listings.

Called inline from the job ingestion pipeline whenever jobs are created or
updated.  For **new** skills (no existing Skill row), a Celery task is
dispatched to generate LLM descriptions asynchronously.

Counter fields (``job_count_30d/1y/5y``, ``growth_pct``, ``avg_salary_usd``,
``is_trending``) are updated incrementally: the current job's data is used
to bump the relevant counters without re-scanning the entire table.
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger('analyzer')


def upsert_skills_for_job(job) -> tuple[list[str], list[str]]:
    """
    Upsert Skill rows for every skill in *job*.skills_required and
    *job*.skills_nice_to_have.

    Returns:
        (new_skill_names, existing_skill_names)
    """
    from analyzer.models import Skill

    raw_skills: set[str] = set()
    for skill_list in (job.skills_required, job.skills_nice_to_have):
        if isinstance(skill_list, list):
            for s in skill_list:
                if isinstance(s, str) and s.strip():
                    raw_skills.add(s.strip().lower())

    if not raw_skills:
        return [], []

    # Build alias lookup for normalisation
    alias_map: dict[str, str] = {}
    for canonical, aliases in Skill.objects.values_list('name', 'aliases'):
        for alias in aliases or []:
            if isinstance(alias, str) and alias.strip():
                alias_map[alias.strip().lower()] = canonical

    normalised: set[str] = set()
    for raw in raw_skills:
        normalised.add(alias_map.get(raw, raw))

    # Figure out which already exist
    existing = set(
        Skill.objects.filter(name__in=normalised).values_list('name', flat=True)
    )
    new_names = normalised - existing

    now = timezone.now()
    job_created = job.created_at or now

    # Determine which time windows this job falls into
    cutoff_30d = now - timedelta(days=30)
    cutoff_1y = now - timedelta(days=365)
    cutoff_5y = now - timedelta(days=365 * 5)

    in_30d = job_created >= cutoff_30d
    in_1y = job_created >= cutoff_1y
    in_5y = job_created >= cutoff_5y

    # Salary for this job (average of min/max)
    job_salary = None
    sal_min = job.salary_min_usd
    sal_max = job.salary_max_usd
    if sal_min and sal_max:
        job_salary = (sal_min + sal_max) / 2
    elif sal_min:
        job_salary = sal_min
    elif sal_max:
        job_salary = sal_max

    # Job title for roles enrichment
    job_title = (job.title or '').strip().lower()

    # ── Create new Skill rows ────────────────────────────────────────
    if new_names:
        to_create = []
        for name in new_names:
            to_create.append(Skill(
                name=name,
                display_name=name.title().replace('_', ' '),
                job_count_5y=1 if in_5y else 0,
                job_count_1y=1 if in_1y else 0,
                job_count_30d=1 if in_30d else 0,
                avg_salary_usd=Decimal(str(round(job_salary, 2))) if job_salary else None,
                roles=[job_title] if job_title else [],
                last_aggregated_at=now,
            ))
        Skill.objects.bulk_create(to_create, ignore_conflicts=True)
        logger.info('Skill enrichment: created %d new skills', len(to_create))

    # ── Update existing Skill rows ───────────────────────────────────
    if existing:
        from django.db.models import F
        update_kwargs = {}
        if in_5y:
            update_kwargs['job_count_5y'] = F('job_count_5y') + 1
        if in_1y:
            update_kwargs['job_count_1y'] = F('job_count_1y') + 1
        if in_30d:
            update_kwargs['job_count_30d'] = F('job_count_30d') + 1

        if update_kwargs:
            update_kwargs['last_aggregated_at'] = now
            Skill.objects.filter(name__in=existing).update(**update_kwargs)

    # ── Update roles on existing skills if job title is new ──────────
    if job_title and existing:
        _add_role_to_skills(existing, job_title)

    return list(new_names), list(existing)


def _add_role_to_skills(skill_names: set[str], role: str):
    """Append *role* to the roles JSON list if not already present."""
    from analyzer.models import Skill

    MAX_ROLES = 10
    for skill in Skill.objects.filter(name__in=skill_names):
        roles = skill.roles or []
        if role not in roles:
            roles.append(role)
            skill.roles = roles[:MAX_ROLES]
            skill.save(update_fields=['roles', 'updated_at'])


def upsert_skills_for_jobs(jobs) -> list[str]:
    """
    Process multiple jobs.  Returns list of new skill names that need
    LLM descriptions.
    """
    all_new: set[str] = set()
    for job in jobs:
        new_names, _ = upsert_skills_for_job(job)
        all_new.update(new_names)
    return list(all_new)
