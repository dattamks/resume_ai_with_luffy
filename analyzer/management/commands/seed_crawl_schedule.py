"""
Management command to seed the daily crawl schedule into django-celery-beat
and default CrawlSource records.

Usage:
    python manage.py seed_crawl_schedule

Admin can then modify the schedule and sources via Django Admin.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed the daily job crawl schedule and default crawl sources'

    def handle(self, *args, **options):
        self._seed_periodic_task()
        self._seed_default_sources()

    def _seed_periodic_task(self):
        """Create or update the crawl-jobs-daily PeriodicTask."""
        from django_celery_beat.models import PeriodicTask, CrontabSchedule

        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute='30',
            hour='20',
            day_of_week='*',
            day_of_month='*',
            month_of_year='*',
            defaults={'timezone': 'UTC'},
        )

        task, created = PeriodicTask.objects.get_or_create(
            name='crawl-jobs-daily',
            defaults={
                'task': 'analyzer.tasks.crawl_jobs_daily_task',
                'crontab': schedule,
                'enabled': True,
                'description': 'Daily job crawl at 2 AM IST (20:30 UTC). Editable via Django Admin.',
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(
                f'Created periodic task: crawl-jobs-daily (crontab: 20:30 UTC)'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'Periodic task crawl-jobs-daily already exists (enabled={task.enabled})'
            ))

    def _seed_default_sources(self):
        """Seed default CrawlSource records if none exist."""
        from analyzer.models import CrawlSource

        if CrawlSource.objects.exists():
            count = CrawlSource.objects.count()
            self.stdout.write(self.style.WARNING(
                f'{count} crawl source(s) already exist — skipping seed'
            ))
            return

        defaults = [
            {
                'name': 'LinkedIn',
                'source_type': CrawlSource.TYPE_JOB_BOARD,
                'url_template': 'https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR=r86400',
                'priority': 1,
            },
            {
                'name': 'Indeed',
                'source_type': CrawlSource.TYPE_JOB_BOARD,
                'url_template': 'https://www.indeed.com/jobs?q={query}&l={location}&fromage=1',
                'priority': 2,
            },
        ]

        for source_data in defaults:
            CrawlSource.objects.create(**source_data)
            self.stdout.write(self.style.SUCCESS(
                f'Created crawl source: {source_data["name"]}'
            ))
