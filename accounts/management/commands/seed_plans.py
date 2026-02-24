"""
Seed default plans for the platform.
Idempotent — safe to run multiple times (uses update_or_create on slug).

Usage:
    python manage.py seed_plans
"""
from django.core.management.base import BaseCommand
from accounts.models import Plan


PLANS = [
    {
        'slug': 'free',
        'name': 'Free',
        'description': 'Get started with basic resume analysis.',
        'billing_cycle': 'free',
        'price': 0,
        'analyses_per_month': 0,  # 0 = unlimited (no limits enforced yet)
        'api_rate_per_hour': 200,
        'max_resume_size_mb': 5,
        'max_resumes_stored': 5,
        'pdf_export': True,
        'share_analysis': True,
        'job_tracking': True,
        'priority_queue': False,
        'email_support': False,
        'is_active': True,
        'display_order': 0,
    },
    {
        'slug': 'pro',
        'name': 'Pro',
        'description': 'Unlimited analyses with priority processing and support.',
        'billing_cycle': 'monthly',
        'price': 499,
        'analyses_per_month': 0,  # 0 = unlimited
        'api_rate_per_hour': 500,
        'max_resume_size_mb': 10,
        'max_resumes_stored': 0,  # unlimited
        'pdf_export': True,
        'share_analysis': True,
        'job_tracking': True,
        'priority_queue': True,
        'email_support': True,
        'is_active': True,
        'display_order': 1,
    },
]


class Command(BaseCommand):
    help = 'Seed default plans (Free + Pro). Idempotent.'

    def handle(self, *args, **options):
        for plan_data in PLANS:
            slug = plan_data.pop('slug')
            obj, created = Plan.objects.update_or_create(
                slug=slug,
                defaults={**plan_data, 'slug': slug},
            )
            # Restore slug for re-runnability
            plan_data['slug'] = slug
            action = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{action}: {obj.name} (₹{obj.price})'))

        self.stdout.write(self.style.SUCCESS('\nDone — plans seeded.'))
