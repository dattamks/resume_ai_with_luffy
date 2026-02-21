import pdfplumber


class PDFExtractor:
    """Extracts plain text from a PDF file."""

    def extract(self, file_path: str) -> str:
        """
        Extract all text from the PDF at `file_path`.
        Returns the concatenated text of all pages.
        Raises ValueError if no text could be extracted.
        """
        text_parts = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())

        if not text_parts:
            raise ValueError(
                'Could not extract text from the uploaded PDF. '
                'Please ensure the file is not a scanned image-only PDF.'
            )

        return '\n\n'.join(text_parts)
