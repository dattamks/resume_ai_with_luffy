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

from .ai_providers.factory import get_openai_client

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

    client = get_openai_client()
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


def compute_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Compute vector embeddings for multiple texts in a single API call.

    The OpenAI embeddings API accepts a list of inputs and returns one
    embedding per input — much faster than N sequential calls.

    Args:
        texts: List of input texts. Each will be truncated to MAX_TEXT_LENGTH.

    Returns:
        List of embedding vectors (same order as input texts).

    Raises:
        ValueError: If API key is not configured or API call fails.
    """
    if not texts:
        return []

    api_key = getattr(settings, 'OPENROUTER_API_KEY', '')
    model = getattr(settings, 'EMBEDDING_MODEL', _DEFAULT_MODEL)

    if not api_key:
        raise ValueError('OPENROUTER_API_KEY is not configured — cannot compute embeddings.')

    # Clean and truncate each text
    clean_texts = []
    valid_indices = []
    for i, text in enumerate(texts):
        clean = text.strip() if text else ''
        if not clean:
            continue
        if len(clean) > _MAX_TEXT_LENGTH:
            clean = clean[:_MAX_TEXT_LENGTH]
        clean_texts.append(clean)
        valid_indices.append(i)

    if not clean_texts:
        raise ValueError('All texts are empty — cannot compute embeddings.')

    client = get_openai_client()
    start = time.monotonic()

    try:
        response = client.embeddings.create(
            model=model,
            input=clean_texts,
        )
        duration = time.monotonic() - start
        logger.info(
            'Batch embeddings computed: model=%s count=%d duration=%.2fs',
            model, len(clean_texts), duration,
        )

        if not response.data or len(response.data) != len(clean_texts):
            raise ValueError(
                f'Embedding API returned {len(response.data) if response.data else 0} '
                f'results for {len(clean_texts)} inputs.'
            )

        # Build result list preserving input order
        # response.data is sorted by index
        embeddings = [None] * len(texts)
        for j, idx in enumerate(valid_indices):
            embeddings[idx] = response.data[j].embedding

        return embeddings

    except Exception as exc:
        duration = time.monotonic() - start
        logger.error('Batch embedding API call failed (%.2fs): %s', duration, type(exc).__name__)
        raise ValueError(f'Batch embedding computation failed: {exc}') from exc


def compute_resume_embedding(resume) -> list[float]:
    """
    Compute an embedding for a resume's text content.

    Uses the resume's own text (populated at upload time) for a clean,
    JD-agnostic embedding. Falls back to analysis text or PDF extraction.

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
    Get resume text for embedding computation.

    Priority:
    1. resume.resume_text (populated at upload time by resume understanding)
    2. Latest completed analysis resume_text (legacy fallback)
    3. PDF extraction (last resort)
    """
    # Primary — upload-time extracted text (since v0.35.0)
    if hasattr(resume, 'resume_text') and resume.resume_text and resume.resume_text.strip():
        return resume.resume_text

    # Fallback — latest completed analysis
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

    # Last resort — extract from PDF
    try:
        from .pdf_extractor import PDFExtractor
        extractor = PDFExtractor()
        text = extractor.extract(resume.file)
        return text
    except Exception as exc:
        logger.warning('PDF extraction failed for resume %s: %s', resume.id, exc)
        return ''
