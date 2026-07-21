"""
Report case-insensitive duplicate user emails.

Run this BEFORE deploying the migration that adds the case-insensitive unique
email index (0023) — that migration will refuse to apply while duplicates exist.

Usage:
    python manage.py check_duplicate_emails
"""
from collections import defaultdict

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Report case-insensitive duplicate user emails (read-only).'

    def handle(self, *args, **options):
        groups = defaultdict(list)
        for user in User.objects.exclude(email='').order_by('id'):
            groups[user.email.strip().lower()].append(user)

        dupes = {email: us for email, us in groups.items() if len(us) > 1}
        if not dupes:
            self.stdout.write(self.style.SUCCESS('No duplicate emails — safe to add the unique constraint.'))
            return

        self.stdout.write(self.style.ERROR(f'Found {len(dupes)} duplicated email(s):\n'))
        for email, us in dupes.items():
            self.stdout.write(f'  {email!r}:')
            for u in us:
                self.stdout.write(
                    f'    - id={u.id} username={u.username!r} '
                    f'joined={u.date_joined:%Y-%m-%d} last_login={u.last_login or "never"}'
                )
        self.stdout.write(self.style.WARNING(
            '\nResolve these (merge/rename/clear the email on the stale accounts) '
            'before running migrate — the unique index cannot be created while '
            'duplicates exist.'
        ))
