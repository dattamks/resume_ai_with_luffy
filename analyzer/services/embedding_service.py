"""
Embedding service for Phase 12 — pgvector similarity matching.

Computes vector embeddings for resume text and job listings using
OpenAI-compatible embeddings API (via OpenRouter or direct).

Uses text-embedding-3-small (1536 dimensions) by default.
Cost: ~$0.02 per 1M tokens — extremely cheap.
"""
import logging
import time

from django.conf import settings
from openai import OpenAI

logger = logging.getLogger('analyzer')

# Default embedding model — configurable via settings
_DEFAULT_MODEL = 'openai/text-embedding-3-small'
_DEFAULT_DIMENSIONS = 1536
_MAX_TEXT_LENGTH = 8000  # characters — ~2K tokens, well within context window


def compute_embedding(text: str) -> list[float]:
    """
    Compute a vector embedding for the given text.

    Args:
        text: Input text to embed. Will be truncated to MAX_TEXT_LENGTH.

    Returns:
        List of floats (embedding vector, 1536 dimensions).

    Raises:
        ValueError: If API key is not configured or API call fails.
    """
    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    base_url = getattr(settings, 'OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
    model = getattr(settings, 'EMBEDDING_MODEL', _DEFAULT_MODEL)

    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured — cannot compute embeddings.')

    # Truncate to limit token usage
    clean_text = text.strip()
    if not clean_text:
        raise ValueError('Empty text — cannot compute embedding.')
    if len(clean_text) > _MAX_TEXT_LENGTH:
        clean_text = clean_text[:_MAX_TEXT_LENGTH]

    client = OpenAI(api_key=api_key, base_url=base_url)
    start = time.monotonic()

    try:
        response = client.embeddings.create(
            model=model,
            input=clean_text,
        )
        duration = time.monotonic() - start
        logger.debug(
            'Embedding computed: model=%s chars=%d duration=%.2fs',
            model, len(clean_text), duration,
        )

        if not response.data or not response.data[0].embedding:
            raise ValueError('Embedding API returned empty data.')

        return response.data[0].embedding

    except Exception as exc:
        duration = time.monotonic() - start
        logger.error('Embedding API call failed (%.2fs): %s', duration, type(exc).__name__)
        raise ValueError(f'Embedding computation failed: {exc}') from exc


def compute_resume_embedding(resume) -> list[float]:
    """
    Compute an embedding for a resume's text content.

    Extracts text from the latest completed analysis or falls back to
    PDF extraction. Stores the embedding on the JobSearchProfile.

    Args:
        resume: Resume model instance.

    Returns:
        List of floats (embedding vector).

    Raises:
        ValueError: If resume has no extractable text.
    """
    resume_text = _get_resume_text(resume)
    if not resume_text or len(resume_text.strip()) < 50:
        raise ValueError(
            f'Resume {resume.id} has insufficient text for embedding. '
            'Upload a readable PDF first.'
        )
    return compute_embedding(resume_text)


def compute_job_embedding(title: str, company: str = '', description: str = '') -> list[float]:
    """
    Compute an embedding for a job listing.

    Concatenates title + company + description snippet for a richer
    representation of the job.

    Args:
        title: Job title.
        company: Company name.
        description: Job description snippet.

    Returns:
        List of floats (embedding vector).
    """
    parts = [title]
    if company:
        parts.append(f'at {company}')
    if description:
        parts.append(description[:500])
    text = ' | '.join(parts)
    return compute_embedding(text)


def _get_resume_text(resume) -> str:
    """
    Get resume text from the latest completed analysis.
    Falls back to PDF extraction if no analysis exists.
    """
    # Try latest completed analysis
    latest = (
        resume.analyses
        .filter(status='done', deleted_at__isnull=True)
        .exclude(resume_text='')
        .order_by('-created_at')
        .values_list('resume_text', flat=True)
        .first()
    )
    if latest:
        return latest

    # Fallback — extract from PDF
    try:
        from .pdf_extractor import PDFExtractor
        extractor = PDFExtractor()
        text = extractor.extract(resume.file)
        return text
    except Exception as exc:
        logger.warning('PDF extraction failed for resume %s: %s', resume.id, exc)
        return ''
