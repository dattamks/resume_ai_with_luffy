"""
Sync Django Plan models with Razorpay.

Creates a Razorpay plan for each active paid Plan that doesn't yet have a
razorpay_plan_id. Use --force to recreate plans even if they already have one.

Usage:
    python manage.py sync_razorpay_plans           # only unsynced plans
    python manage.py sync_razorpay_plans --force    # recreate all
    python manage.py sync_razorpay_plans --dry-run  # preview without changes
"""
from django.core.management.base import BaseCommand

from accounts.models import Plan
from accounts.razorpay_service import sync_razorpay_plan


class Command(BaseCommand):
    help = 'Create Razorpay plans for active paid Django Plans'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Recreate Razorpay plans even if razorpay_plan_id is already set',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview which plans would be synced without making API calls',
        )

    def handle(self, *args, **options):
        force = options['force']
        dry_run = options['dry_run']

        plans = Plan.objects.filter(is_active=True).exclude(price=0)

        if not force:
            plans = plans.filter(razorpay_plan_id='')

        if not plans.exists():
            self.stdout.write(self.style.SUCCESS('All plans are already synced.'))
            return

        self.stdout.write(f'Found {plans.count()} plan(s) to sync:\n')

        synced = 0
        errors = 0

        for plan in plans:
            label = f'  {plan.name} ({plan.billing_cycle}, ₹{plan.price})'

            if dry_run:
                self.stdout.write(f'{label} → would sync')
                continue

            try:
                old_id = plan.razorpay_plan_id
                new_id = sync_razorpay_plan(plan, force=force)
                self.stdout.write(self.style.SUCCESS(
                    f'{label} → {new_id}'
                    + (f' (was {old_id})' if old_id else ''),
                ))
                synced += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'{label} → ERROR: {e}'))
                errors += 1

        if dry_run:
            self.stdout.write(f'\nDry run complete. {plans.count()} plan(s) would be synced.')
        else:
            self.stdout.write(f'\nDone: {synced} synced, {errors} errors.')
