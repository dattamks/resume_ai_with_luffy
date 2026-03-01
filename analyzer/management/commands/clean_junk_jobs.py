"""
Management command to remove junk / garbage DiscoveredJob records.

Targets:
  1. Error-page titles  ("Sorry, we couldn't find anything here", "404", etc.)
  2. Placeholder titles  (title == "Jobs", blank, or < 5 meaningful chars)
  3. Duplicate URL rows   (same url → keep newest, delete older)

Usage:
    python manage.py clean_junk_jobs             # dry-run (preview only)
    python manage.py clean_junk_jobs --apply      # actually delete
    python manage.py clean_junk_jobs --apply -v2  # verbose
"""
from django.core.management.base import BaseCommand
from django.db.models import Q, Count, Min
from django.db.models.functions import Length


# ── Patterns that indicate a failed / empty crawl ──────────────────
JUNK_TITLE_KEYWORDS = [
    'sorry',
    "couldn't find",
    'could not find',
    'not found',
    'no results',
    'page not',
    '404',
    'access denied',
    'forbidden',
    'unavailable',
    'no jobs',
    'no positions',
    'no openings',
    'something went wrong',
    'error loading',
]

# Exact titles that are clearly placeholders
PLACEHOLDER_EXACT = [
    'jobs',
    'careers',
    'open positions',
    'job openings',
]


class Command(BaseCommand):
    help = 'Remove junk / garbage DiscoveredJob records (dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually delete the records. Without this flag, only previews.',
        )
        parser.add_argument(
            '--min-title-len',
            type=int,
            default=5,
            help='Minimum title length (shorter titles considered junk). Default: 5',
        )

    def handle(self, *args, **options):
        from analyzer.models import DiscoveredJob

        apply = options['apply']
        min_len = options['min_title_len']
        verbosity = options['verbosity']

        mode = self.style.ERROR('LIVE — records will be deleted') if apply else \
            self.style.WARNING('DRY-RUN — nothing will be deleted. Pass --apply to delete.')
        self.stdout.write(f'\nMode: {mode}\n')

        total_before = DiscoveredJob.objects.count()
        to_delete_ids = set()

        # ── 1. Keyword-based junk titles ────────────────────────
        q = Q()
        for kw in JUNK_TITLE_KEYWORDS:
            q |= Q(title__icontains=kw)
        junk_qs = DiscoveredJob.objects.filter(q)
        junk_count = junk_qs.count()
        self.stdout.write(f'\n1) Junk titles (error/empty page keywords): {junk_count}')
        if verbosity >= 2:
            for j in junk_qs[:30]:
                self.stdout.write(f'     [{j.company}] {j.title}')
        to_delete_ids.update(junk_qs.values_list('id', flat=True))

        # ── 2. Placeholder / too-short titles ───────────────────
        placeholder_q = Q(title__in=[p.title() for p in PLACEHOLDER_EXACT]) | \
            Q(title__in=PLACEHOLDER_EXACT) | \
            Q(title__in=[p.upper() for p in PLACEHOLDER_EXACT])
        placeholder_qs = DiscoveredJob.objects.filter(placeholder_q)
        placeholder_count = placeholder_qs.count()
        self.stdout.write(f'2) Placeholder titles (exact match): {placeholder_count}')
        if verbosity >= 2:
            for j in placeholder_qs[:20]:
                self.stdout.write(f'     [{j.company}] "{j.title}"')
        to_delete_ids.update(placeholder_qs.values_list('id', flat=True))

        short_qs = DiscoveredJob.objects.annotate(
            tlen=Length('title'),
        ).filter(tlen__gt=0, tlen__lt=min_len).exclude(id__in=to_delete_ids)
        short_count = short_qs.count()
        self.stdout.write(f'3) Short titles (< {min_len} chars): {short_count}')
        if verbosity >= 2:
            for j in short_qs[:20]:
                self.stdout.write(f'     [{j.company}] "{j.title}"')
        to_delete_ids.update(short_qs.values_list('id', flat=True))

        # ── 3. Blank titles ─────────────────────────────────────
        blank_qs = DiscoveredJob.objects.filter(Q(title='') | Q(title__isnull=True))
        blank_count = blank_qs.count()
        self.stdout.write(f'4) Blank/null titles: {blank_count}')
        to_delete_ids.update(blank_qs.values_list('id', flat=True))

        # ── 4. Duplicate URL (keep newest) ──────────────────────
        dup_urls = (
            DiscoveredJob.objects
            .values('url')
            .annotate(n=Count('id'), keep=Min('created_at'))  # keep oldest by default? No, keep newest.
            .filter(n__gt=1)
        )
        dup_delete_count = 0
        for dup in dup_urls:
            # Keep the newest record, delete the rest
            dupes = DiscoveredJob.objects.filter(url=dup['url']).order_by('-created_at')
            ids_to_remove = list(dupes.values_list('id', flat=True)[1:])  # skip first (newest)
            to_delete_ids.update(ids_to_remove)
            dup_delete_count += len(ids_to_remove)
        self.stdout.write(f'5) Duplicate URLs (keeping newest): {dup_delete_count}')

        # ── Summary ─────────────────────────────────────────────
        unique_count = len(to_delete_ids)
        self.stdout.write(f'\n{"=" * 50}')
        self.stdout.write(f'Total records to delete: {unique_count} / {total_before}')
        self.stdout.write(f'Records remaining after: {total_before - unique_count}')

        if unique_count == 0:
            self.stdout.write(self.style.SUCCESS('\nDatabase is clean — nothing to delete.'))
            return

        if apply:
            deleted_count, _ = DiscoveredJob.objects.filter(id__in=to_delete_ids).delete()
            self.stdout.write(self.style.SUCCESS(f'\nDeleted {deleted_count} junk records.'))
            remaining = DiscoveredJob.objects.count()
            self.stdout.write(f'Remaining jobs: {remaining}')
        else:
            self.stdout.write(self.style.WARNING(
                '\nRe-run with --apply to actually delete these records.'
            ))
