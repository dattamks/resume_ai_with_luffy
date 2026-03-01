"""
Management command to print a health report for the jobs database.

Checks for all known edge cases and prints a summary with counts
and actionable recommendations.

Usage:
    python manage.py job_health_report
    python manage.py job_health_report -v2     # show sample records
"""
from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from django.db.models.functions import Length


# Same junk keywords as clean_junk_jobs for consistency
JUNK_TITLE_KEYWORDS = [
    'sorry', "couldn't find", 'could not find', 'not found',
    'no results', 'page not', '404', 'access denied', 'forbidden',
    'unavailable', 'no jobs', 'no positions', 'no openings',
    'something went wrong', 'error loading',
]

PLACEHOLDER_EXACT = ['jobs', 'careers', 'open positions', 'job openings']


class Command(BaseCommand):
    help = 'Print a health report for the DiscoveredJob database'

    def handle(self, *args, **options):
        from analyzer.models import DiscoveredJob, Company, CompanyEntity

        verbosity = options['verbosity']
        issues = []

        total = DiscoveredJob.objects.count()
        self.stdout.write(f'\n{"=" * 60}')
        self.stdout.write(f'  JOB DATABASE HEALTH REPORT')
        self.stdout.write(f'{"=" * 60}')
        self.stdout.write(f'\nTotal DiscoveredJobs:  {total}')
        self.stdout.write(f'Total Companies:       {Company.objects.count()}')
        self.stdout.write(f'Total CompanyEntities: {CompanyEntity.objects.count()}')

        if total == 0:
            self.stdout.write(self.style.WARNING('\nNo jobs in database — nothing to report.'))
            return

        # ── 1. Junk titles ──────────────────────────────────────
        q = Q()
        for kw in JUNK_TITLE_KEYWORDS:
            q |= Q(title__icontains=kw)
        junk_count = DiscoveredJob.objects.filter(q).count()
        status = self._check(junk_count, 0, 'Junk titles (error pages)')
        issues.append(('Junk titles', junk_count, 'clean_junk_jobs'))
        if verbosity >= 2 and junk_count:
            for j in DiscoveredJob.objects.filter(q)[:5]:
                self.stdout.write(f'     [{j.company}] {j.title}')

        # ── 2. Placeholder titles ───────────────────────────────
        all_placeholders = PLACEHOLDER_EXACT + \
            [p.title() for p in PLACEHOLDER_EXACT] + \
            [p.upper() for p in PLACEHOLDER_EXACT]
        ph_count = DiscoveredJob.objects.filter(title__in=all_placeholders).count()
        self._check(ph_count, 0, 'Placeholder titles ("Jobs", "Careers")')
        issues.append(('Placeholder titles', ph_count, 'clean_junk_jobs'))

        # ── 3. Short titles ────────────────────────────────────
        short_count = DiscoveredJob.objects.annotate(
            tlen=Length('title'),
        ).filter(tlen__gt=0, tlen__lt=5).count()
        self._check(short_count, 0, 'Short titles (< 5 chars)')
        issues.append(('Short titles', short_count, 'clean_junk_jobs'))

        # ── 4. Blank titles ────────────────────────────────────
        blank_count = DiscoveredJob.objects.filter(
            Q(title='') | Q(title__isnull=True),
        ).count()
        self._check(blank_count, 0, 'Blank/null titles')
        issues.append(('Blank titles', blank_count, 'clean_junk_jobs'))

        # ── 5. Duplicate URLs ──────────────────────────────────
        dup_urls = (
            DiscoveredJob.objects
            .values('url')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
            .count()
        )
        self._check(dup_urls, 0, 'Duplicate URL groups')
        issues.append(('Duplicate URLs', dup_urls, 'clean_junk_jobs'))

        # ── 6. Missing embeddings ──────────────────────────────
        no_emb = DiscoveredJob.objects.filter(embedding__isnull=True).count()
        self._check(no_emb, 0, 'Jobs missing embeddings')
        issues.append(('Missing embeddings', no_emb, 'backfill_embeddings'))

        # ── 7. Unlinked CompanyEntity ──────────────────────────
        unlinked = DiscoveredJob.objects.filter(company_entity__isnull=True).count()
        self._check(unlinked, 0, 'Jobs not linked to CompanyEntity')
        issues.append(('Unlinked CompanyEntity', unlinked, 'populate_company_entities'))

        # ── 8. Blank company names ─────────────────────────────
        no_co = DiscoveredJob.objects.filter(
            Q(company='') | Q(company__isnull=True),
        ).count()
        self._check(no_co, 0, 'Jobs with blank company name')
        issues.append(('Blank company', no_co, None))

        # ── 9. Jobs by source breakdown ────────────────────────
        self.stdout.write(f'\n  Source breakdown:')
        for row in DiscoveredJob.objects.values('source').annotate(n=Count('id')).order_by('-n'):
            self.stdout.write(f'    {row["source"]:<20} {row["n"]:>6} jobs')

        # ── 10. Top companies ──────────────────────────────────
        self.stdout.write(f'\n  Top 5 companies:')
        for row in DiscoveredJob.objects.values('company').annotate(
            n=Count('id'),
        ).order_by('-n')[:5]:
            self.stdout.write(f'    {row["company"]:<30} {row["n"]:>4} jobs')

        # ── Summary ─────────────────────────────────────────────
        actionable = [(name, count, cmd) for name, count, cmd in issues if count > 0 and cmd]
        self.stdout.write(f'\n{"=" * 60}')
        if not actionable:
            self.stdout.write(self.style.SUCCESS('  ALL CHECKS PASSED — database is healthy!'))
        else:
            self.stdout.write(self.style.WARNING('  RECOMMENDED ACTIONS:'))
            # Group by command
            by_cmd = {}
            for name, count, cmd in actionable:
                by_cmd.setdefault(cmd, []).append((name, count))
            for cmd, items in by_cmd.items():
                desc = ', '.join(f'{name} ({count})' for name, count in items)
                self.stdout.write(f'    python manage.py {cmd} --apply')
                self.stdout.write(f'      → fixes: {desc}')
        self.stdout.write(f'{"=" * 60}\n')

    def _check(self, count, expected, label):
        if count <= expected:
            self.stdout.write(self.style.SUCCESS(f'  ✓ {label}: {count}'))
        else:
            self.stdout.write(self.style.ERROR(f'  ✗ {label}: {count}'))
        return count
