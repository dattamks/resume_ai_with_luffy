"""
Enforce case-insensitive email uniqueness at the database level.

Django's auth User model does not make `email` unique; uniqueness was only
checked in serializers (racy, and bypassable by admin/other code paths). This
adds a partial, case-insensitive unique index on `auth_user(LOWER(email))` for
non-empty emails.

Before creating the index we assert there are no existing case-insensitive
duplicates (run `python manage.py check_duplicate_emails` to inspect) — creating
the index would otherwise fail with a cryptic IntegrityError, so we fail early
with an actionable message instead.

The expression + partial index syntax used here is supported by both PostgreSQL
and SQLite (>= 3.9), so it applies on prod and the SQLite test database alike.
"""
from django.db import migrations

_INDEX_NAME = 'uniq_auth_user_email_ci'


def _assert_no_duplicate_emails(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    seen = {}
    dupes = set()
    for uid, email in User.objects.exclude(email='').values_list('id', 'email'):
        key = (email or '').strip().lower()
        if not key:
            continue
        if key in seen:
            dupes.add(key)
        else:
            seen[key] = uid
    if dupes:
        raise RuntimeError(
            f'Cannot add unique email index: {len(dupes)} case-insensitive '
            f'duplicate email(s) exist. Run `python manage.py '
            f'check_duplicate_emails` and resolve them first.'
        )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0022_grandfather_email_verified'),
        # Depend on the latest auth migration: on SQLite, an auth migration that
        # alters auth_user rebuilds the table and would drop our custom index if
        # it ran afterward. Ordering after all auth changes keeps the index.
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(_assert_no_duplicate_emails, _noop_reverse),
        migrations.RunSQL(
            sql=(
                f'CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME} '
                f"ON auth_user (LOWER(email)) WHERE email <> '';"
            ),
            reverse_sql=f'DROP INDEX IF EXISTS {_INDEX_NAME};',
        ),
    ]
