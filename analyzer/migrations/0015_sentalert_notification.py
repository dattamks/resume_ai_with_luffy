"""
Phase 12B — SentAlert and Notification models.

Creates:
1. SentAlert — dedup log to prevent resending the same job to the same user
2. Notification — in-app notification store for the notification bell/badge
"""
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0014_pgvector_embeddings'),
        ('auth', '__latest__'),
    ]

    operations = [
        # SentAlert model
        migrations.CreateModel(
            name='SentAlert',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('channel', models.CharField(
                    choices=[('email', 'Email'), ('in_app', 'In-App')],
                    max_length=20,
                    help_text='Notification channel used',
                )),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sent_alerts',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('discovered_job', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sent_alerts',
                    to='analyzer.discoveredjob',
                )),
            ],
            options={
                'ordering': ['-sent_at'],
                'verbose_name': 'Sent Alert',
                'verbose_name_plural': 'Sent Alerts',
            },
        ),
        migrations.AddConstraint(
            model_name='sentalert',
            constraint=models.UniqueConstraint(
                fields=['user', 'discovered_job', 'channel'],
                name='unique_sent_alert_per_channel',
            ),
        ),
        migrations.AddIndex(
            model_name='sentalert',
            index=models.Index(fields=['user', '-sent_at'], name='sentalert_user_sent_idx'),
        ),

        # Notification model
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('body', models.TextField(blank=True)),
                ('link', models.CharField(max_length=2048, blank=True, help_text='Relative URL or external link')),
                ('is_read', models.BooleanField(default=False, db_index=True)),
                ('notification_type', models.CharField(
                    max_length=30,
                    choices=[
                        ('job_match', 'Job Match'),
                        ('analysis_done', 'Analysis Complete'),
                        ('resume_generated', 'Resume Generated'),
                        ('system', 'System'),
                    ],
                    db_index=True,
                )),
                ('metadata', models.JSONField(default=dict, blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='notifications',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Notification',
                'verbose_name_plural': 'Notifications',
            },
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', '-created_at'], name='notification_user_created_idx'),
        ),
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(fields=['user', 'is_read', '-created_at'], name='notification_user_unread_idx'),
        ),
    ]
