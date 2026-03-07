"""
HTML → PDF resume rendering bridge.

Each function renders a Jinja2 HTML template and converts to PDF via
Playwright headless Chromium.  Falls back to the legacy ReportLab
renderer if Playwright/Chromium is unavailable (local dev without
Chromium installed).

All functions share the signature: ``(resume_content: dict) -> bytes``
"""
import logging

logger = logging.getLogger(__name__)


def _render_html_pdf(template_name: str, resume_content: dict) -> bytes:
    """Render a Jinja2 HTML template to PDF via Playwright."""
    from .resume_template_env import render_template
    from .resume_html_renderer import render_html_to_pdf

    html = render_template(template_name, resume_content)
    return render_html_to_pdf(html)


def render_ats_classic_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('ats_classic.html', resume_content)


def render_modern_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('modern.html', resume_content)


def render_executive_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('executive.html', resume_content)


def render_creative_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('creative.html', resume_content)


def render_minimal_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('minimal.html', resume_content)


def render_modern_luxe_html_pdf(resume_content: dict) -> bytes:
    return _render_html_pdf('modern_luxe.html', resume_content)
