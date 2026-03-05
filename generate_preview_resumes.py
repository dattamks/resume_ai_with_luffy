#!/usr/bin/env python
"""
One-off script: generate 5 PDF resumes (one per template) for analysis 16,
upload to R2, and print signed URLs.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resume_ai.settings')
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '/tmp/pw-browsers')
django.setup()

from django.core.files.base import ContentFile
from analyzer.models import ResumeAnalysis, GeneratedResume
from analyzer.services.template_registry import get_renderer
from analyzer.services.resume_html_renderer import shutdown_browser

ANALYSIS_PK = 16
TEMPLATES = ['ats_classic', 'modern', 'executive', 'creative', 'minimal']


def main():
    a = ResumeAnalysis.objects.get(pk=ANALYSIS_PK)
    resume_content = a.parsed_content
    user = a.user

    # Step 1: Render all PDFs first (Playwright creates an event loop)
    pdfs = {}
    for tmpl in TEMPLATES:
        print(f'Rendering {tmpl}...')
        renderer = get_renderer(tmpl, 'pdf')
        pdf_bytes = renderer(resume_content)
        print(f'  PDF size: {len(pdf_bytes)} bytes')
        pdfs[tmpl] = pdf_bytes

    # Shut down Playwright before touching DB (avoids async context conflict)
    shutdown_browser()
    print('\nPlaywright shut down. Saving to R2...\n')

    # Step 2: Save to DB + R2
    results = []
    name_slug = resume_content.get('contact', {}).get('name', 'resume').replace(' ', '_')

    for tmpl in TEMPLATES:
        gen = GeneratedResume.objects.create(
            analysis=a,
            user=user,
            template=tmpl,
            format='pdf',
            resume_content=resume_content,
            status='done',
            credits_deducted=False,
        )
        filename = f'{name_slug}_{tmpl}_v3_{gen.pk}.pdf'
        gen.file.save(filename, ContentFile(pdfs[tmpl]))
        gen.save()
        url = gen.file.url
        print(f'{tmpl}: saved ({len(pdfs[tmpl])} bytes)')
        results.append((tmpl, str(gen.pk), url))

    print('\n=== DOWNLOAD LINKS (signed, 1-hour expiry) ===\n')
    for tmpl, pk, url in results:
        print(f'**{tmpl}**:\n{url}\n')


if __name__ == '__main__':
    main()
