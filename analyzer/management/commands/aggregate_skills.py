"""
Management command to aggregate skills from DiscoveredJob listings into
the normalised ``Skill`` catalogue.

Usage:
    python manage.py aggregate_skills               # aggregate only
    python manage.py aggregate_skills --generate-descriptions   # also LLM-generate descriptions
    python manage.py aggregate_skills --generate-descriptions --batch-size 50
    python manage.py aggregate_skills --top 500      # only process top N by demand
    python manage.py aggregate_skills --dry-run      # preview without writing

Idempotent — safe to run repeatedly.  Designed to be called from a
periodic Celery beat task (e.g. daily).
"""
import json
import logging
import time
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Avg, Q
from django.utils import timezone

from analyzer.models import DiscoveredJob, Skill

logger = logging.getLogger('analyzer')

# ── LLM prompt for batch skill description + category generation ─────────

SKILL_DESCRIPTION_SYSTEM_PROMPT = (
    'You are a technical career expert. For each skill name provided, '
    'return a JSON array of objects with:\n'
    '- "name": the skill name (exactly as given, lowercase)\n'
    '- "display_name": proper capitalisation (e.g. "kubernetes" → "Kubernetes")\n'
    '- "description": 1-2 sentence description of what this skill/technology is '
    'and why it matters in the job market\n'
    '- "category": one of: language, framework, tool, cloud, data, devops, '
    'design, soft, security, mobile, ai_ml, other\n'
    '- "roles": list of 2-5 common job roles that use this skill '
    '(e.g. ["backend engineer", "devops engineer"])\n\n'
    'Return ONLY a valid JSON array. No markdown, no code fences, no explanation.'
)


def _generate_descriptions_batch(skill_names: list[str]) -> list[dict]:
    """
    Call LLM to generate descriptions, categories, and roles for a batch
    of skill names.  Returns a list of dicts keyed by 'name'.
    """
    from analyzer.services.ai_providers.factory import get_openai_client, llm_retry

    client = get_openai_client()
    model = getattr(settings, 'OPENROUTER_MODEL', 'anthropic/claude-3.5-haiku')

    prompt = (
        f'Generate descriptions for these {len(skill_names)} skills:\n\n'
        + json.dumps(skill_names)
    )

    @llm_retry
    def _call():
        return client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': SKILL_DESCRIPTION_SYSTEM_PROMPT},
                {'role': 'user', 'content': prompt},
            ],
            max_tokens=4096,
            temperature=0.2,
            timeout=120,
        )

    response = _call()
    raw = response.choices[0].message.content.strip() if response.choices else ''

    # Strip markdown fences if present
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1] if '\n' in raw else raw[3:]
        if raw.endswith('```'):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning('Failed to parse LLM response for skill descriptions: %s', raw[:500])
        return []


class Command(BaseCommand):
    help = 'Aggregate skills from DiscoveredJob listings into the Skill catalogue.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--generate-descriptions', action='store_true',
            help='Use LLM to generate descriptions for skills that lack one.',
        )
        parser.add_argument(
            '--batch-size', type=int, default=30,
            help='Number of skills per LLM batch call (default: 30).',
        )
        parser.add_argument(
            '--top', type=int, default=0,
            help='Only process top N skills by 30-day demand (0 = all).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Preview aggregated counts without writing to DB.',
        )
        parser.add_argument(
            '--trending-threshold', type=int, default=50,
            help='Top N skills by 30d demand to mark as trending (default: 50).',
        )

    def handle(self, *args, **options):
        generate_descs = options['generate_descriptions']
        batch_size = options['batch_size']
        top_n = options['top']
        dry_run = options['dry_run']
        trending_threshold = options['trending_threshold']

        now = timezone.now()
        cutoff_30d = now - timedelta(days=30)
        cutoff_60d = now - timedelta(days=60)
        cutoff_1y = now - timedelta(days=365)
        cutoff_5y = now - timedelta(days=365 * 5)

        self.stdout.write('Aggregating skills from DiscoveredJob listings...')

        # ── Step 1: Count skills across time windows ──────────────────────
        counter_30d: Counter = Counter()
        counter_prev_30d: Counter = Counter()
        counter_1y: Counter = Counter()
        counter_5y: Counter = Counter()
        salary_sums: dict[str, list] = {}  # skill → list of avg salaries

        # Build alias lookup from existing Skill rows
        alias_map: dict[str, str] = {}  # alias_lower → canonical name
        for skill_obj in Skill.objects.values_list('name', 'aliases'):
            canonical, aliases = skill_obj
            for alias in (aliases or []):
                if isinstance(alias, str) and alias.strip():
                    alias_map[alias.strip().lower()] = canonical

        def _normalise(raw_name: str) -> str:
            """Normalise a raw skill string to its canonical name."""
            lower = raw_name.strip().lower()
            return alias_map.get(lower, lower)

        def _process_jobs(qs, counter):
            """Aggregate skills from a queryset into a counter."""
            for skills_req, skills_nice, sal_min, sal_max in qs.values_list(
                'skills_required', 'skills_nice_to_have',
                'salary_min_usd', 'salary_max_usd',
            ):
                seen_in_job = set()
                for skill_list in (skills_req, skills_nice):
                    if not isinstance(skill_list, list):
                        continue
                    for s in skill_list:
                        if isinstance(s, str) and s.strip():
                            name = _normalise(s)
                            if name not in seen_in_job:
                                counter[name] += 1
                                seen_in_job.add(name)
                # Salary tracking (only for 30d window)
                if counter is counter_30d and (sal_min or sal_max):
                    avg_sal = None
                    if sal_min and sal_max:
                        avg_sal = (sal_min + sal_max) / 2
                    elif sal_min:
                        avg_sal = sal_min
                    elif sal_max:
                        avg_sal = sal_max
                    if avg_sal:
                        for name in seen_in_job:
                            salary_sums.setdefault(name, []).append(float(avg_sal))

        # 30-day window
        qs_30d = DiscoveredJob.objects.filter(created_at__gte=cutoff_30d)
        _process_jobs(qs_30d, counter_30d)
        self.stdout.write(f'  30d: {len(counter_30d)} unique skills from {qs_30d.count()} jobs')

        # Previous 30-day window (for growth %)
        qs_prev = DiscoveredJob.objects.filter(created_at__gte=cutoff_60d, created_at__lt=cutoff_30d)
        _process_jobs(qs_prev, counter_prev_30d)

        # 1-year window
        qs_1y = DiscoveredJob.objects.filter(created_at__gte=cutoff_1y)
        _process_jobs(qs_1y, counter_1y)
        self.stdout.write(f'  1y:  {len(counter_1y)} unique skills from {qs_1y.count()} jobs')

        # 5-year window
        qs_5y = DiscoveredJob.objects.filter(created_at__gte=cutoff_5y)
        _process_jobs(qs_5y, counter_5y)
        self.stdout.write(f'  5y:  {len(counter_5y)} unique skills from {qs_5y.count()} jobs')

        # Merge all skill names
        all_skills = set(counter_30d) | set(counter_1y) | set(counter_5y)
        self.stdout.write(f'  Total unique skills: {len(all_skills)}')

        if top_n:
            # Keep only top N by 30d demand
            top_names = {s for s, _ in counter_30d.most_common(top_n)}
            all_skills = all_skills & top_names
            self.stdout.write(f'  Filtered to top {top_n}: {len(all_skills)} skills')

        if dry_run:
            self.stdout.write(self.style.WARNING('\n[DRY RUN] Top 30 skills by 30d demand:'))
            for name, count in counter_30d.most_common(30):
                growth = None
                prev = counter_prev_30d.get(name, 0)
                if prev > 0:
                    growth = ((count - prev) / prev) * 100
                growth_str = f'{growth:+.1f}%' if growth is not None else 'N/A'
                self.stdout.write(f'  {name:30s}  30d={count:5d}  1y={counter_1y.get(name, 0):6d}  growth={growth_str}')
            return

        # ── Step 2: Upsert Skill rows ────────────────────────────────────
        created_count = 0
        updated_count = 0
        trending_names = {s for s, _ in counter_30d.most_common(trending_threshold)}

        # Pre-fetch existing skills in one query
        existing_skills = {s.name: s for s in Skill.objects.filter(name__in=all_skills)}

        to_create = []
        to_update = []
        update_fields = [
            'job_count_30d', 'job_count_1y', 'job_count_5y',
            'growth_pct', 'avg_salary_usd', 'is_trending',
            'last_aggregated_at', 'updated_at',
        ]

        for name in all_skills:
            count_30d = counter_30d.get(name, 0)
            count_1y = counter_1y.get(name, 0)
            count_5y = counter_5y.get(name, 0)
            prev_30d = counter_prev_30d.get(name, 0)

            growth = None
            if prev_30d > 0:
                growth = ((count_30d - prev_30d) / prev_30d) * 100

            avg_salary = None
            if name in salary_sums and salary_sums[name]:
                avg_salary = Decimal(str(round(sum(salary_sums[name]) / len(salary_sums[name]), 2)))

            if name in existing_skills:
                skill_obj = existing_skills[name]
                skill_obj.job_count_30d = count_30d
                skill_obj.job_count_1y = count_1y
                skill_obj.job_count_5y = count_5y
                skill_obj.growth_pct = growth
                skill_obj.avg_salary_usd = avg_salary
                skill_obj.is_trending = name in trending_names
                skill_obj.last_aggregated_at = now
                skill_obj.updated_at = now
                to_update.append(skill_obj)
            else:
                to_create.append(Skill(
                    name=name,
                    display_name=name.title().replace('_', ' '),
                    job_count_30d=count_30d,
                    job_count_1y=count_1y,
                    job_count_5y=count_5y,
                    growth_pct=growth,
                    avg_salary_usd=avg_salary,
                    is_trending=name in trending_names,
                    last_aggregated_at=now,
                ))

        if to_create:
            Skill.objects.bulk_create(to_create, batch_size=500)
            created_count = len(to_create)

        if to_update:
            Skill.objects.bulk_update(to_update, update_fields, batch_size=500)
            updated_count = len(to_update)

        self.stdout.write(self.style.SUCCESS(
            f'Skill catalogue updated: {created_count} created, {updated_count} updated.'
        ))

        # ── Step 3: LLM-generate descriptions for skills missing them ────
        if generate_descs:
            needs_desc = list(
                Skill.objects.filter(
                    Q(description='') | Q(description__isnull=True),
                    is_active=True,
                ).order_by('-job_count_30d').values_list('name', flat=True)
            )

            if not needs_desc:
                self.stdout.write('All skills already have descriptions.')
                return

            self.stdout.write(f'Generating descriptions for {len(needs_desc)} skills...')

            for i in range(0, len(needs_desc), batch_size):
                batch = needs_desc[i:i + batch_size]
                self.stdout.write(f'  Batch {i // batch_size + 1}: {len(batch)} skills')

                try:
                    results = _generate_descriptions_batch(batch)
                except Exception as e:
                    self.stderr.write(f'  LLM batch failed: {e}')
                    continue

                for item in results:
                    if not isinstance(item, dict) or 'name' not in item:
                        continue
                    name = item['name'].strip().lower()
                    try:
                        skill_obj = Skill.objects.get(name=name)
                    except Skill.DoesNotExist:
                        continue

                    update_fields = ['updated_at']
                    if item.get('description') and not skill_obj.description:
                        skill_obj.description = item['description']
                        update_fields.append('description')
                    if item.get('display_name'):
                        skill_obj.display_name = item['display_name']
                        update_fields.append('display_name')
                    if item.get('category') and item['category'] in dict(Skill.CATEGORY_CHOICES):
                        skill_obj.category = item['category']
                        update_fields.append('category')
                    if item.get('roles') and isinstance(item['roles'], list):
                        skill_obj.roles = item['roles']
                        update_fields.append('roles')

                    skill_obj.save(update_fields=update_fields)

                # Rate-limit between batches
                if i + batch_size < len(needs_desc):
                    time.sleep(1)

            desc_count = Skill.objects.exclude(description='').count()
            self.stdout.write(self.style.SUCCESS(
                f'Descriptions generated. {desc_count} skills now have descriptions.'
            ))
