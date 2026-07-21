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
        'cost': 0,
        'description': 'Job alert runs are free — limited by max_job_alerts on plan instead.',
    },
    {
        'action': 'interview_prep',
        'cost': 0,
        'description': 'Interview prep from the question bank — no LLM, free.',
    },
    {
        'action': 'interview_prep_ai',
        'cost': 1,
        'description': 'Interview prep LLM fallback (used only when the question bank is empty).',
    },
    {
        'action': 'cover_letter',
        'cost': 1,
        'description': 'Cost per AI-generated cover letter.',
    },
    {
        'action': 'resume_builder',
        'cost': 2,
        'description': 'Entry charge to start a conversational resume-builder session.',
    },
    {
        'action': 'chat_ai_action',
        'cost': 1,
        'description': 'Per AI-backed action inside a builder chat (rewrite, structure, message). '
                       'Credits act as the usage ceiling — when they run out, AI actions stop.',
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
