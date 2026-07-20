"""
Grandfather existing users to email-verified.

REQUIRE_EMAIL_VERIFICATION starts enforcing the verified-email gate on
high-value actions. Users who registered before this shouldn't be locked out,
so mark every existing profile as verified. New users created after this
migration keep the model default (False) and must verify.
"""
from django.db import migrations


def mark_existing_verified(apps, schema_editor):
    UserProfile = apps.get_model('accounts', 'UserProfile')
    UserProfile.objects.filter(is_email_verified=False).update(is_email_verified=True)


def noop(apps, schema_editor):
    # Irreversible by design — we can't know which users were unverified before.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0021_alter_plan_max_job_alerts'),
    ]

    operations = [
        migrations.RunPython(mark_existing_verified, noop),
    ]
