"""
Management command to backfill embeddings for DiscoveredJob records
that are missing them.

Usage:
    python manage.py backfill_embeddings             # dry-run
    python manage.py backfill_embeddings --apply      # compute and save
    python manage.py backfill_embeddings --apply --batch-size=50
"""
import time
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Compute embeddings for DiscoveredJob records that are missing them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='Actually compute and save embeddings.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of texts per API call. Default: 100.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max jobs to process (0 = all). Default: 0.',
        )

    def handle(self, *args, **options):
        from analyzer.models import DiscoveredJob

        apply = options['apply']
        batch_size = options['batch_size']
        limit = options['limit']

        mode = self.style.ERROR('LIVE — embeddings will be computed') if apply else \
            self.style.WARNING('DRY-RUN — nothing will change. Pass --apply to execute.')
        self.stdout.write(f'\nMode: {mode}\n')

        missing_qs = DiscoveredJob.objects.filter(embedding__isnull=True).order_by('created_at')
        total_missing = missing_qs.count()
        total_all = DiscoveredJob.objects.count()

        self.stdout.write(f'Jobs missing embeddings: {total_missing} / {total_all}')

        if total_missing == 0:
            self.stdout.write(self.style.SUCCESS('All jobs already have embeddings!'))
            return

        if not apply:
            self.stdout.write(self.style.WARNING(
                f'\nWould compute embeddings for {total_missing} jobs '
                f'in batches of {batch_size}.\n'
                f'Re-run with --apply to execute.'
            ))
            return

        # ── Import embedding service ────────────────────────────
        try:
            from analyzer.services.embedding_service import compute_embeddings_batch
        except ImportError:
            self.stderr.write(self.style.ERROR(
                'Could not import compute_embeddings_batch. '
                'Make sure analyzer/services/embedding_service.py exists.'
            ))
            return

        if limit > 0:
            missing_qs = missing_qs[:limit]
            total_missing = min(total_missing, limit)

        self.stdout.write(f'Processing {total_missing} jobs in batches of {batch_size}...\n')

        processed = 0
        errors = 0
        start_time = time.time()

        # Collect all jobs (materialise queryset to allow batching)
        job_ids = list(missing_qs.values_list('id', flat=True))

        for i in range(0, len(job_ids), batch_size):
            batch_ids = job_ids[i:i + batch_size]
            batch_jobs = list(DiscoveredJob.objects.filter(id__in=batch_ids))

            # Build text representations
            texts = []
            for job in batch_jobs:
                skills = ', '.join(job.skills_required or [])
                text = f"{job.title} at {job.company}. {job.description_snippet}. Skills: {skills}"
                texts.append(text.strip())

            try:
                embeddings = compute_embeddings_batch(texts)

                if len(embeddings) != len(batch_jobs):
                    self.stderr.write(self.style.ERROR(
                        f'  Batch {i // batch_size + 1}: got {len(embeddings)} '
                        f'embeddings for {len(batch_jobs)} jobs — skipping'
                    ))
                    errors += len(batch_jobs)
                    continue

                # Save each embedding
                for job, emb in zip(batch_jobs, embeddings):
                    job.embedding = emb
                    job.save(update_fields=['embedding'])

                processed += len(batch_jobs)
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                self.stdout.write(
                    f'  Batch {i // batch_size + 1}: '
                    f'{len(batch_jobs)} done | '
                    f'Total: {processed}/{total_missing} | '
                    f'{rate:.1f} jobs/sec'
                )

            except Exception as e:
                self.stderr.write(self.style.ERROR(
                    f'  Batch {i // batch_size + 1} failed: {e}'
                ))
                errors += len(batch_jobs)
                continue

        # ── Summary ─────────────────────────────────────────────
        elapsed = time.time() - start_time
        still_missing = DiscoveredJob.objects.filter(embedding__isnull=True).count()

        self.stdout.write(f'\n{"=" * 50}')
        self.stdout.write(f'Processed: {processed}')
        self.stdout.write(f'Errors:    {errors}')
        self.stdout.write(f'Time:      {elapsed:.1f}s')
        self.stdout.write(f'Still missing embeddings: {still_missing}')

        if still_missing == 0:
            self.stdout.write(self.style.SUCCESS('\nAll jobs now have embeddings!'))
        elif errors:
            self.stdout.write(self.style.WARNING(
                f'\n{still_missing} jobs still missing — re-run to retry failed batches.'
            ))
