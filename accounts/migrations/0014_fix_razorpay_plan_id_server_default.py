"""
Fix razorpay_plan_id column on accounts_plan: set server-side DEFAULT ''
and convert any existing NULL values to ''.

Django's AddField with default='' only sets the default at the ORM level.
PostgreSQL still has no column DEFAULT, so inserts that bypass the ORM
(or edge cases in admin) can produce NULL → IntegrityError.
"""

from django.db import migrations


def fix_server_default(apps, schema_editor):
    """Only run ALTER on PostgreSQL; SQLite handles defaults differently."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        "ALTER TABLE accounts_plan ALTER COLUMN razorpay_plan_id SET DEFAULT '';"
    )
    schema_editor.execute(
        "UPDATE accounts_plan SET razorpay_plan_id = '' WHERE razorpay_plan_id IS NULL;"
    )


def reverse_fix(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        "ALTER TABLE accounts_plan ALTER COLUMN razorpay_plan_id DROP DEFAULT;"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_add_social_links_to_userprofile"),
    ]

    operations = [
        migrations.RunPython(fix_server_default, reverse_fix),
    ]
