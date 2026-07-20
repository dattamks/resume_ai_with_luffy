import io
import logging

import pdfplumber
from django.conf import settings

logger = logging.getLogger('analyzer')


class PDFExtractor:
    """Extracts plain text from a PDF file (local or remote/R2)."""

    # PDF magic bytes: every valid PDF starts with %PDF
    _PDF_MAGIC = b'%PDF'

    def _max_bytes(self) -> int:
        """Hard byte cap for a PDF we're willing to load into memory."""
        # Allow a little slack over the configured resume size limit.
        mb = getattr(settings, 'MAX_RESUME_SIZE_MB', 5)
        return int(mb * 1024 * 1024 * 1.2)

    def _check_size(self, num_bytes: int) -> None:
        limit = self._max_bytes()
        if num_bytes > limit:
            raise ValueError(
                f'The uploaded PDF is too large ({num_bytes // (1024 * 1024)} MB). '
                f'Please upload a file under {getattr(settings, "MAX_RESUME_SIZE_MB", 5)} MB.'
            )

    def _validate_pdf_magic(self, data: bytes) -> None:
        """Check that the file starts with the PDF magic bytes (%PDF)."""
        if not data[:4].startswith(self._PDF_MAGIC):
            raise ValueError(
                'The uploaded file is not a valid PDF. '
                'Please upload a PDF document.'
            )

    # High-signal "active content" markers. A résumé exported from Word / LaTeX
    # / Canva / a browser never contains these; their presence indicates an
    # embedded script, launch action, or embedded file — reject before parsing.
    # (Best-effort heuristic, not a substitute for a real AV scanner: it catches
    # markers in uncompressed catalog objects, the common malicious case.)
    _ACTIVE_CONTENT_MARKERS = (
        b'/JavaScript', b'/JS', b'/Launch', b'/EmbeddedFile',
        b'/RichMedia', b'/XFA', b'/AA',
    )

    def _scan_active_content(self, raw: bytes) -> None:
        if not getattr(settings, 'PDF_REJECT_ACTIVE_CONTENT', True):
            return
        found = [m.decode() for m in self._ACTIVE_CONTENT_MARKERS if m in raw]
        if found:
            logger.warning('PDFExtractor: rejected active-content PDF (markers=%s)', found)
            raise ValueError(
                'This PDF contains active content (scripts, launch actions, or '
                'embedded files) and was rejected for security. Please upload a '
                'plain PDF exported from your resume editor.'
            )

    def extract(self, file_field) -> str:
        """
        Extract all text from a PDF.

        Args:
            file_field: A Django FieldFile (FileField value), file path string,
                        or file-like object. Works with both local storage and
                        remote backends (S3/R2).

        Returns:
            Concatenated text of all pages.

        Raises:
            ValueError: If no text could be extracted or file is not a PDF.
        """
        text_parts = []

        # Determine how to open the PDF
        if isinstance(file_field, str):
            # Plain file path (backward compat / local dev)
            import os
            logger.debug('PDFExtractor: opening local path %s', file_field)
            try:
                self._check_size(os.path.getsize(file_field))
            except OSError:
                pass  # size unknown — magic/parse checks still apply
            with open(file_field, 'rb') as f:
                raw = f.read()
            self._validate_pdf_magic(raw[:8])
            self._scan_active_content(raw)
            pdf_source = file_field
        elif hasattr(file_field, 'open'):
            # Django FieldFile — works with local and R2/S3 storage.
            # Cap the size BEFORE reading the whole file into memory when the
            # backend can report it, to avoid OOM on a huge/bomb upload.
            size = getattr(file_field, 'size', None)
            if isinstance(size, int):
                self._check_size(size)
            logger.debug('PDFExtractor: reading from storage backend')
            try:
                file_field.open('rb')
                raw = file_field.read()
            finally:
                file_field.close()
            self._check_size(len(raw))
            self._validate_pdf_magic(raw[:8])
            self._scan_active_content(raw)
            pdf_source = io.BytesIO(raw)
        else:
            # Generic file-like object — read it fully so we can validate the
            # magic bytes and scan for active content, then hand pdfplumber a
            # fresh BytesIO.
            if hasattr(file_field, 'seek'):
                pos = file_field.tell()
                raw = file_field.read()
                file_field.seek(pos)
                self._check_size(len(raw))
                self._validate_pdf_magic(raw[:8])
                self._scan_active_content(raw)
                pdf_source = io.BytesIO(raw)
            else:
                pdf_source = file_field

        try:
            pdf_ctx = pdfplumber.open(pdf_source)
        except Exception as exc:
            # Encrypted/password-protected or otherwise unparseable PDF.
            msg = str(exc).lower()
            if 'password' in msg or 'encrypt' in msg:
                raise ValueError(
                    'This PDF is password-protected. Please remove the password '
                    'and upload an unlocked copy.'
                )
            raise ValueError(
                'Could not open the uploaded PDF — it may be corrupted or in an '
                'unsupported format.'
            )

        with pdf_ctx as pdf:
            total_pages = len(pdf.pages)
            max_pages = getattr(settings, 'MAX_PDF_PAGES', 50)
            logger.debug('PDFExtractor: PDF has %d page(s)', total_pages)

            if total_pages > max_pages:
                raise ValueError(
                    f'PDF has {total_pages} pages, which exceeds the maximum of {max_pages}. '
                    'Please upload a shorter document.'
                )

            for i, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
                    logger.debug('PDFExtractor: page %d — %d chars', i, len(page_text))
                else:
                    logger.debug('PDFExtractor: page %d — no text found', i)

        if not text_parts:
            raise ValueError(
                'Could not extract text from the uploaded PDF. '
                'Please ensure the file is not a scanned image-only PDF.'
            )

        result = '\n\n'.join(text_parts)
        logger.debug('PDFExtractor: total extracted: %d chars from %d page(s)', len(result), len(text_parts))
        return result
