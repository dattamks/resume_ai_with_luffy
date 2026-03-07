"""
Serializers for one-click tailored resume generation from a crawled job.
"""
from rest_framework import serializers


class TailorResumeSerializer(serializers.Serializer):
    """Input for POST /api/v1/jobs/<job_id>/tailor-resume/."""

    resume_id = serializers.UUIDField(
        required=False,
        help_text='UUID of the resume to tailor. Defaults to user\'s default resume.',
    )
    template = serializers.SlugField(
        max_length=50,
        default='ats_classic',
        help_text='Template slug (e.g. ats_classic, modern_clean).',
    )
    format = serializers.ChoiceField(
        choices=['pdf', 'docx'],
        default='pdf',
        help_text='Output format: pdf or docx.',
    )
