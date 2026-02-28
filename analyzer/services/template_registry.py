"""
Resume template renderer registry.

Maps template slugs to their PDF/DOCX rendering functions.
Each renderer accepts a ``resume_content: dict`` and returns ``bytes``.

Adding a new template:
1. Create ``resume_<slug>_pdf.py`` and ``resume_<slug>_docx.py`` in this package.
2. Register them in ``TEMPLATE_RENDERERS`` below.
3. Create a ``ResumeTemplate`` row via Django Admin or ``seed_templates`` command.
"""

from __future__ import annotations

from typing import Callable, Dict

# Lazy imports to avoid loading all renderers at module level.
# Each value is a dict with 'pdf' and 'docx' callables.

RendererFn = Callable[[dict], bytes]


def _get_ats_classic_pdf() -> RendererFn:
    from .resume_pdf_renderer import render_resume_pdf
    return render_resume_pdf


def _get_ats_classic_docx() -> RendererFn:
    from .resume_docx_renderer import render_resume_docx
    return render_resume_docx


def _get_modern_pdf() -> RendererFn:
    from .resume_modern_pdf import render_modern_pdf
    return render_modern_pdf


def _get_modern_docx() -> RendererFn:
    from .resume_modern_docx import render_modern_docx
    return render_modern_docx


def _get_executive_pdf() -> RendererFn:
    from .resume_executive_pdf import render_executive_pdf
    return render_executive_pdf


def _get_executive_docx() -> RendererFn:
    from .resume_executive_docx import render_executive_docx
    return render_executive_docx


def _get_creative_pdf() -> RendererFn:
    from .resume_creative_pdf import render_creative_pdf
    return render_creative_pdf


def _get_creative_docx() -> RendererFn:
    from .resume_creative_docx import render_creative_docx
    return render_creative_docx


def _get_minimal_pdf() -> RendererFn:
    from .resume_minimal_pdf import render_minimal_pdf
    return render_minimal_pdf


def _get_minimal_docx() -> RendererFn:
    from .resume_minimal_docx import render_minimal_docx
    return render_minimal_docx


# ── Registry ────────────────────────────────────────────────────────────────

TEMPLATE_RENDERERS: Dict[str, Dict[str, Callable[[], RendererFn]]] = {
    'ats_classic': {'pdf': _get_ats_classic_pdf, 'docx': _get_ats_classic_docx},
    'modern':      {'pdf': _get_modern_pdf,      'docx': _get_modern_docx},
    'executive':   {'pdf': _get_executive_pdf,    'docx': _get_executive_docx},
    'creative':    {'pdf': _get_creative_pdf,     'docx': _get_creative_docx},
    'minimal':     {'pdf': _get_minimal_pdf,      'docx': _get_minimal_docx},
}


def get_renderer(template_slug: str, fmt: str) -> RendererFn:
    """
    Look up the renderer function for a template + format combination.

    Args:
        template_slug: e.g. ``'ats_classic'``, ``'modern'``
        fmt: ``'pdf'`` or ``'docx'``

    Returns:
        A callable: ``(resume_content: dict) -> bytes``

    Raises:
        ValueError: If template slug or format is not registered.
    """
    entry = TEMPLATE_RENDERERS.get(template_slug)
    if entry is None:
        available = ', '.join(sorted(TEMPLATE_RENDERERS.keys()))
        raise ValueError(
            f'Unknown template "{template_slug}". Available: {available}'
        )

    getter = entry.get(fmt)
    if getter is None:
        raise ValueError(
            f'Format "{fmt}" not available for template "{template_slug}". '
            f'Available formats: {", ".join(entry.keys())}'
        )

    return getter()


def get_available_slugs() -> list[str]:
    """Return sorted list of all registered template slugs."""
    return sorted(TEMPLATE_RENDERERS.keys())
