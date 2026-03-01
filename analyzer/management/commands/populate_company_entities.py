"""
Management command to populate CompanyEntity from DiscoveredJob records.

For every unique company name found in DiscoveredJob.company:
  1. Find or create a Company (parent brand)
  2. Find or create a CompanyEntity (defaults to a single global entity)
  3. Link the DiscoveredJob.company_entity FK

This bridges the gap where the crawler stores company as a plain-text
field but the richer Company → CompanyEntity hierarchy is empty.

Usage:
    python manage.py populate_company_entities             # dry-run
    python manage.py populate_company_entities --apply      # actually create
    python manage.py populate_company_entities --apply -v2  # verbose
"""
from django.core.management.base import BaseCommand
from django.db.models import Q, Count
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Create Company + CompanyEntity records from DiscoveredJob.company names and link them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually create records and update FKs. Without this, only previews.',
        )
        parser.add_argument(
            '--country',
            type=str,
            default='Unknown',
            help='Default operating country for new entities. Default: "Unknown".',
        )

    def handle(self, *args, **options):
        from analyzer.models import DiscoveredJob, Company, CompanyEntity

        apply = options['apply']
        default_country = options['country']
        verbosity = options['verbosity']

        mode = self.style.ERROR('LIVE — records will be created/updated') if apply else \
            self.style.WARNING('DRY-RUN — nothing will change. Pass --apply to execute.')
        self.stdout.write(f'\nMode: {mode}\n')

        # ── Gather unique company names from jobs ───────────────
        company_names = (
            DiscoveredJob.objects
            .exclude(Q(company='') | Q(company__isnull=True))
            .values_list('company', flat=True)
            .distinct()
        )
        company_names = sorted(set(company_names))
        self.stdout.write(f'Unique company names in DiscoveredJob: {len(company_names)}')

        # Already-linked jobs
        already_linked = DiscoveredJob.objects.exclude(company_entity=None).count()
        total_jobs = DiscoveredJob.objects.count()
        self.stdout.write(f'Jobs already linked to CompanyEntity: {already_linked} / {total_jobs}')

        companies_created = 0
        entities_created = 0
        jobs_linked = 0
        skipped = 0

        for name in company_names:
            name_clean = name.strip()
            if not name_clean:
                skipped += 1
                continue

            slug = slugify(name_clean) or name_clean.lower().replace(' ', '-')

            if verbosity >= 2:
                self.stdout.write(f'  Processing: {name_clean} (slug: {slug})')

            if apply:
                # ── 1. Find or create Company ───────────────────
                company_obj, co_created = Company.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'name': name_clean,
                        'description': '',
                        'is_active': True,
                    },
                )
                if co_created:
                    companies_created += 1
                    if verbosity >= 2:
                        self.stdout.write(self.style.SUCCESS(f'    + Company created: {name_clean}'))

                # ── 2. Find or create CompanyEntity ─────────────
                entity, ent_created = CompanyEntity.objects.get_or_create(
                    company=company_obj,
                    operating_country=default_country,
                    display_name=name_clean,
                    defaults={
                        'legal_name': '',
                        'is_headquarters': True,
                        'is_active': True,
                    },
                )
                if ent_created:
                    entities_created += 1
                    if verbosity >= 2:
                        self.stdout.write(self.style.SUCCESS(f'    + Entity created: {name_clean} ({default_country})'))

                # ── 3. Link all matching jobs ───────────────────
                updated = (
                    DiscoveredJob.objects
                    .filter(company=name, company_entity__isnull=True)
                    .update(company_entity=entity)
                )
                jobs_linked += updated
                if verbosity >= 2 and updated:
                    self.stdout.write(f'    → Linked {updated} job(s)')
            else:
                # Dry-run: count what would happen
                job_count = DiscoveredJob.objects.filter(
                    company=name, company_entity__isnull=True,
                ).count()
                co_exists = Company.objects.filter(slug=slug).exists()
                ent_exists = CompanyEntity.objects.filter(
                    company__slug=slug,
                    operating_country=default_country,
                    display_name=name_clean,
                ).exists()

                if not co_exists:
                    companies_created += 1
                if not ent_exists:
                    entities_created += 1
                jobs_linked += job_count

                if verbosity >= 2:
                    status_parts = []
                    if not co_exists:
                        status_parts.append('new Company')
                    if not ent_exists:
                        status_parts.append('new Entity')
                    status_parts.append(f'{job_count} jobs to link')
                    self.stdout.write(f'  {name_clean}: {", ".join(status_parts)}')

        # ── Summary ─────────────────────────────────────────────
        self.stdout.write(f'\n{"=" * 50}')
        self.stdout.write(f'Companies to create:       {companies_created}')
        self.stdout.write(f'CompanyEntities to create: {entities_created}')
        self.stdout.write(f'Jobs to link:              {jobs_linked}')
        if skipped:
            self.stdout.write(f'Skipped (blank names):     {skipped}')

        if apply:
            co_total = Company.objects.count()
            ent_total = CompanyEntity.objects.count()
            linked_total = DiscoveredJob.objects.exclude(company_entity=None).count()
            self.stdout.write(self.style.SUCCESS(
                f'\nDone. Companies={co_total}, Entities={ent_total}, '
                f'Linked jobs={linked_total}/{DiscoveredJob.objects.count()}'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                '\nRe-run with --apply to actually create/link these records.'
            ))
