# Generated for idempotent credit operations.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_add_geo_fields_to_userprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="wallettransaction",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Optional dedup key. When set, a second attempt to write a "
                    "transaction with the same key is a no-op (enforced by a "
                    "partial unique constraint). Used to make refunds and credit "
                    "grants idempotent against retries and duplicate webhook "
                    "deliveries."
                ),
                max_length=120,
            ),
        ),
        migrations.AddConstraint(
            model_name="wallettransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("idempotency_key", ""), _negated=True),
                fields=("idempotency_key",),
                name="uniq_wallet_txn_idempotency_key",
            ),
        ),
    ]
