"""Add fields for one-click tailored resume from crawled job.

- DiscoveredJob.full_description: stores full scraped JD text
- GeneratedResume.source_job: FK to DiscoveredJob that triggered generation
- GeneratedResume.verification_score: post-generation ATS re-check score
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('analyzer', '0038_add_display_name_to_resume'),
    ]

    operations = [
        migrations.AddField(
            model_name='discoveredjob',
            name='full_description',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Full job description scraped from the posting URL',
            ),
        ),
        migrations.AddField(
            model_name='generatedresume',
            name='source_job',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='tailored_resumes',
                to='analyzer.discoveredjob',
                help_text='The crawled job that triggered this tailored resume generation',
            ),
        ),
        migrations.AddField(
            model_name='generatedresume',
            name='verification_score',
            field=models.PositiveSmallIntegerField(
                null=True,
                blank=True,
                help_text='Post-generation ATS score from re-analysis verification',
            ),
        ),
    ]
