import io
import logging

import pdfplumber
from django.conf import settings

logger = logging.getLogger('analyzer')


class PDFExtractor:
    """Extracts plain text from a PDF file (local or remote/R2)."""

    # PDF magic bytes: every valid PDF starts with %PDF
    _PDF_MAGIC = b'%PDF'

    def _validate_pdf_magic(self, data: bytes) -> None:
        """Check that the file starts with the PDF magic bytes (%PDF)."""
        if not data[:4].startswith(self._PDF_MAGIC):
            raise ValueError(
                'The uploaded file is not a valid PDF. '
                'Please upload a PDF document.'
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
            logger.debug('PDFExtractor: opening local path %s', file_field)
            # Validate magic bytes for local files
            with open(file_field, 'rb') as f:
                self._validate_pdf_magic(f.read(8))
            pdf_source = file_field
        elif hasattr(file_field, 'open'):
            # Django FieldFile — works with local and R2/S3 storage
            logger.debug('PDFExtractor: reading from storage backend')
            try:
                file_field.open('rb')
                raw = file_field.read()
            finally:
                file_field.close()
            self._validate_pdf_magic(raw[:8])
            pdf_source = io.BytesIO(raw)
        else:
            # Generic file-like object
            if hasattr(file_field, 'seek'):
                pos = file_field.tell()
                header = file_field.read(8)
                file_field.seek(pos)
                self._validate_pdf_magic(header)
            pdf_source = file_field

        with pdfplumber.open(pdf_source) as pdf:
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
