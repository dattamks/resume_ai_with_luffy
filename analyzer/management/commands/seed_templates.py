"""
Management command to seed the 5 default resume templates.

Usage:
    python manage.py seed_templates

Idempotent — uses get_or_create by slug, so running twice is safe.
"""
from django.core.management.base import BaseCommand

from analyzer.models import ResumeTemplate


TEMPLATES = [
    {
        'slug': 'ats_classic',
        'name': 'ATS Classic',
        'description': (
            'Clean single-column layout optimised for Applicant Tracking Systems. '
            'Standard section headings, no graphics, serif/sans-serif font pairing. '
            'Best for traditional industries and large corporations.'
        ),
        'category': 'professional',
        'is_premium': False,
        'sort_order': 0,
    },
    {
        'slug': 'modern',
        'name': 'Modern Clean',
        'description': (
            'Contemporary design with teal accent colours, dot-separated contact info, '
            'and coloured section dividers. Perfect for tech, startups, and creative-adjacent roles.'
        ),
        'category': 'professional',
        'is_premium': True,
        'sort_order': 1,
    },
    {
        'slug': 'executive',
        'name': 'Executive',
        'description': (
            'Formal, authoritative layout with dark charcoal header, serif typography (Times), '
            'and uppercase name. Ideal for senior management, C-suite, and leadership positions.'
        ),
        'category': 'executive',
        'is_premium': True,
        'sort_order': 2,
    },
    {
        'slug': 'creative',
        'name': 'Creative',
        'description': (
            'Vibrant purple-themed design with coloured section headers, emoji contact icons, '
            'and arrow bullet points. Great for designers, marketers, and creative professionals.'
        ),
        'category': 'creative',
        'is_premium': True,
        'sort_order': 3,
    },
    {
        'slug': 'minimal',
        'name': 'Minimal',
        'description': (
            'Ultra-clean layout with generous whitespace, no borders or decorative elements, '
            'and muted grey accents. Perfect for candidates who want a calm, distraction-free resume.'
        ),
        'category': 'professional',
        'is_premium': True,
        'sort_order': 4,
    },
]


class Command(BaseCommand):
    help = 'Seed the default resume templates (idempotent).'

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for tmpl_data in TEMPLATES:
            slug = tmpl_data.pop('slug')
            obj, created = ResumeTemplate.objects.get_or_create(
                slug=slug,
                defaults=tmpl_data,
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {obj.name} ({slug})'))
            else:
                # Update existing fields (except slug)
                changed = False
                for key, value in tmpl_data.items():
                    if getattr(obj, key) != value:
                        setattr(obj, key, value)
                        changed = True
                if changed:
                    obj.save()
                    updated_count += 1
                    self.stdout.write(self.style.WARNING(f'  Updated: {obj.name} ({slug})'))
                else:
                    self.stdout.write(f'  Exists: {obj.name} ({slug})')
            # Restore slug key for idempotency on re-runs
            tmpl_data['slug'] = slug

        self.stdout.write(self.style.SUCCESS(
            f'\nDone: {created_count} created, {updated_count} updated, '
            f'{len(TEMPLATES) - created_count - updated_count} unchanged.'
        ))
