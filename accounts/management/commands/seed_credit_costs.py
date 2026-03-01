"""
Seed default credit costs for the platform.
Idempotent — safe to run multiple times (uses update_or_create on action).

Usage:
    python manage.py seed_credit_costs
"""
from django.core.management.base import BaseCommand
from accounts.models import CreditCost


CREDIT_COSTS = [
    {
        'action': 'resume_analysis',
        'cost': 1,
        'description': 'Cost per resume analysis (including retries that succeed).',
    },
    {
        'action': 'resume_generation',
        'cost': 1,
        'description': 'Cost per AI-generated improved resume from analysis report.',
    },
    {
        'action': 'job_alert_run',
        'cost': 1,
        'description': 'Cost per job alert discovery + matching run (automated or manual).',
    },
    {
        'action': 'interview_prep',
        'cost': 1,
        'description': 'Cost per AI-generated interview preparation from analysis.',
    },
    {
        'action': 'cover_letter',
        'cost': 1,
        'description': 'Cost per AI-generated cover letter from analysis.',
    },
    {
        'action': 'resume_builder',
        'cost': 2,
        'description': 'Cost per resume created via the conversational resume builder.',
    },
]


class Command(BaseCommand):
    help = 'Seed default credit costs. Idempotent.'

    def handle(self, *args, **options):
        for cost_data in CREDIT_COSTS:
            action = cost_data.pop('action')
            obj, created = CreditCost.objects.update_or_create(
                action=action,
                defaults={**cost_data, 'action': action},
            )
            # Restore action for re-runnability
            cost_data['action'] = action
            status = 'Created' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{status}: {obj.action} = {obj.cost} credits'))

        self.stdout.write(self.style.SUCCESS('\nDone — credit costs seeded.'))
