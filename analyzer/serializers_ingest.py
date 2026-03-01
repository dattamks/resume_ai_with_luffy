"""
Serializers for the Crawler Bot Ingest API.

These endpoints are called by the external crawler service (not by users).
Authentication is via a shared ``X-Crawler-Key`` header.
"""

from rest_framework import serializers

from .models import (
    Company, CompanyEntity, CompanyCareerPage, CrawlSource,
    DiscoveredJob, UserCompanyFollow,
)


# ── Company Ingest ───────────────────────────────────────────────────────────


class CompanyIngestSerializer(serializers.ModelSerializer):
    """
    Upsert a Company by ``name``.

    The crawler sends company data; the backend creates or updates
    the record keyed on the unique ``name`` field.
    ``slug`` is auto-generated if not provided.
    """

    class Meta:
        model = Company
        fields = (
            'name', 'slug', 'description', 'logo', 'industry',
            'founded_year', 'company_size',
            'headquarters_country', 'headquarters_city',
            'linkedin_url', 'glassdoor_url', 'tech_stack',
            'is_active',
        )
        extra_kwargs = {
            'slug': {'required': False},
            'is_active': {'required': False},
        }

    def validate_name(self, value):
        return value.strip()

    def create(self, validated_data):
        from django.utils.text import slugify
        name = validated_data['name']
        if not validated_data.get('slug'):
            validated_data['slug'] = slugify(name)
        company, _created = Company.objects.update_or_create(
            name=name,
            defaults=validated_data,
        )
        return company


class CompanyEntityIngestSerializer(serializers.ModelSerializer):
    """
    Upsert a CompanyEntity.

    Requires ``company_name`` (resolved to FK) + ``display_name`` + ``operating_country``.
    """
    company_name = serializers.CharField(
        max_length=255, write_only=True,
        help_text='Company brand name — must already exist.',
    )

    class Meta:
        model = CompanyEntity
        fields = (
            'company_name', 'legal_name', 'display_name',
            'operating_country', 'operating_city',
            'is_headquarters', 'is_indian_entity',
            'website', 'is_active',
        )
        extra_kwargs = {
            'is_active': {'required': False},
            'is_headquarters': {'required': False},
            'is_indian_entity': {'required': False},
        }

    def validate_company_name(self, value):
        try:
            return Company.objects.get(name__iexact=value.strip())
        except Company.DoesNotExist:
            raise serializers.ValidationError(
                f'Company "{value}" does not exist. Ingest the company first.'
            )

    def create(self, validated_data):
        company = validated_data.pop('company_name')
        display_name = validated_data['display_name']
        operating_country = validated_data['operating_country']
        entity, _created = CompanyEntity.objects.update_or_create(
            company=company,
            display_name=display_name,
            operating_country=operating_country,
            defaults=validated_data,
        )
        return entity


class CompanyCareerPageIngestSerializer(serializers.ModelSerializer):
    """
    Upsert a CompanyCareerPage.

    Requires ``company_name`` + ``entity_display_name`` + ``entity_country``
    to resolve the parent CompanyEntity.
    """
    company_name = serializers.CharField(max_length=255, write_only=True)
    entity_display_name = serializers.CharField(max_length=255, write_only=True)
    entity_country = serializers.CharField(max_length=100, write_only=True)

    class Meta:
        model = CompanyCareerPage
        fields = (
            'company_name', 'entity_display_name', 'entity_country',
            'url', 'label', 'country', 'crawl_frequency', 'is_active',
        )
        extra_kwargs = {
            'is_active': {'required': False},
            'crawl_frequency': {'required': False},
        }

    def validate(self, attrs):
        company_name = attrs.pop('company_name', '').strip()
        entity_display = attrs.pop('entity_display_name', '').strip()
        entity_country = attrs.pop('entity_country', '').strip()
        try:
            entity = CompanyEntity.objects.select_related('company').get(
                company__name__iexact=company_name,
                display_name__iexact=entity_display,
                operating_country__iexact=entity_country,
            )
        except CompanyEntity.DoesNotExist:
            raise serializers.ValidationError(
                f'CompanyEntity "{entity_display}" in "{entity_country}" '
                f'under company "{company_name}" not found. '
                'Ingest the company and entity first.'
            )
        attrs['_entity'] = entity
        return attrs

    def create(self, validated_data):
        entity = validated_data.pop('_entity')
        url = validated_data['url']
        page, _created = CompanyCareerPage.objects.update_or_create(
            entity=entity,
            url=url,
            defaults=validated_data,
        )
        return page


# ── Job Ingest ───────────────────────────────────────────────────────────────


class DiscoveredJobIngestSerializer(serializers.ModelSerializer):
    """
    Upsert a DiscoveredJob by ``(source, external_id)``.

    Optionally links to a CompanyEntity via ``company_entity_display_name``
    + ``company_entity_country``.
    """
    company_entity_display_name = serializers.CharField(
        max_length=255, required=False, write_only=True, allow_blank=True,
        help_text='Display name of the CompanyEntity to link (optional).',
    )
    company_entity_country = serializers.CharField(
        max_length=100, required=False, write_only=True, allow_blank=True,
        help_text='Operating country of the CompanyEntity (required if display_name given).',
    )

    class Meta:
        model = DiscoveredJob
        fields = (
            'source', 'external_id', 'source_page_url', 'url',
            'title', 'company', 'location', 'salary_range',
            'description_snippet',
            'skills_required', 'skills_nice_to_have',
            'experience_years_min', 'experience_years_max',
            'employment_type', 'remote_policy', 'seniority_level',
            'industry', 'education_required',
            'salary_min_usd', 'salary_max_usd',
            'posted_at', 'raw_data',
            # lookup fields
            'company_entity_display_name', 'company_entity_country',
        )
        extra_kwargs = {
            'source_page_url': {'required': False},
            'title': {'required': False},
            'company': {'required': False},
            'location': {'required': False},
            'salary_range': {'required': False},
            'description_snippet': {'required': False},
            'skills_required': {'required': False},
            'skills_nice_to_have': {'required': False},
            'experience_years_min': {'required': False},
            'experience_years_max': {'required': False},
            'employment_type': {'required': False},
            'remote_policy': {'required': False},
            'seniority_level': {'required': False},
            'industry': {'required': False},
            'education_required': {'required': False},
            'salary_min_usd': {'required': False},
            'salary_max_usd': {'required': False},
            'posted_at': {'required': False},
            'raw_data': {'required': False},
        }

    def validate(self, attrs):
        entity_name = attrs.pop('company_entity_display_name', '').strip()
        entity_country = attrs.pop('company_entity_country', '').strip()
        if entity_name and entity_country:
            try:
                entity = CompanyEntity.objects.get(
                    display_name__iexact=entity_name,
                    operating_country__iexact=entity_country,
                )
                attrs['company_entity'] = entity
            except CompanyEntity.DoesNotExist:
                pass  # Non-fatal — job is still saved without entity link
        return attrs

    def create(self, validated_data):
        source = validated_data['source']
        external_id = validated_data['external_id']
        job, _created = DiscoveredJob.objects.update_or_create(
            source=source,
            external_id=external_id,
            defaults=validated_data,
        )
        return job


class DiscoveredJobBulkIngestSerializer(serializers.Serializer):
    """
    Accept a list of jobs in a single API call for efficient bulk ingestion.
    """
    jobs = DiscoveredJobIngestSerializer(many=True)

    def create(self, validated_data):
        results = []
        for job_data in validated_data['jobs']:
            serializer = DiscoveredJobIngestSerializer(data={})
            # Use validated data directly since parent already validated
            job, _created = DiscoveredJob.objects.update_or_create(
                source=job_data['source'],
                external_id=job_data['external_id'],
                defaults=job_data,
            )
            results.append({'id': str(job.id), 'external_id': job.external_id, 'created': _created})
        return results


# ── CrawlSource ──────────────────────────────────────────────────────────────


class CrawlSourceSerializer(serializers.ModelSerializer):
    """Read-only serializer so the crawler can fetch active sources."""

    class Meta:
        model = CrawlSource
        fields = (
            'id', 'name', 'source_type', 'url_template',
            'is_active', 'priority', 'last_crawled_at',
        )
        read_only_fields = fields


class CrawlSourceUpdateSerializer(serializers.Serializer):
    """Allows the crawler to report last_crawled_at after a successful crawl."""
    last_crawled_at = serializers.DateTimeField()


# ── Company read serializers (for crawler to fetch company data) ─────────────


class CompanyReadSerializer(serializers.ModelSerializer):
    """Read serializer for Company."""

    class Meta:
        model = Company
        fields = (
            'id', 'name', 'slug', 'description', 'logo', 'industry',
            'founded_year', 'company_size',
            'headquarters_country', 'headquarters_city',
            'linkedin_url', 'glassdoor_url', 'tech_stack',
            'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = fields


class CompanyEntityReadSerializer(serializers.ModelSerializer):
    """Read serializer for CompanyEntity with nested career pages."""
    company_name = serializers.CharField(source='company.name', read_only=True)
    career_pages = serializers.SerializerMethodField()

    class Meta:
        model = CompanyEntity
        fields = (
            'id', 'company', 'company_name', 'legal_name', 'display_name',
            'operating_country', 'operating_city',
            'is_headquarters', 'is_indian_entity',
            'website', 'is_active',
            'career_pages',
            'created_at', 'updated_at',
        )
        read_only_fields = fields

    def get_career_pages(self, obj):
        pages = obj.career_pages.filter(is_active=True)
        return CompanyCareerPageReadSerializer(pages, many=True).data


class CompanyCareerPageReadSerializer(serializers.ModelSerializer):
    """Read serializer for CompanyCareerPage."""

    class Meta:
        model = CompanyCareerPage
        fields = (
            'id', 'url', 'label', 'country',
            'crawl_frequency', 'is_active', 'last_crawled_at',
        )
        read_only_fields = fields
