import pdfplumber


class PDFExtractor:
    """Extracts plain text from a PDF file."""

    def extract(self, file_path: str) -> str:
        """
        Extract all text from the PDF at `file_path`.
        Returns the concatenated text of all pages.
        Raises ValueError if no text could be extracted.
        """
        print(f'[DEBUG]   PDFExtractor: opening {file_path}')
        text_parts = []

        with pdfplumber.open(file_path) as pdf:
            print(f'[DEBUG]   PDFExtractor: PDF has {len(pdf.pages)} page(s)')
            for i, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text.strip())
                    print(f'[DEBUG]   PDFExtractor: page {i} — {len(page_text)} chars extracted')
                else:
                    print(f'[DEBUG]   PDFExtractor: page {i} — no text found')

        if not text_parts:
            print(f'[DEBUG]   PDFExtractor: ❌ No text extracted from any page')
            raise ValueError(
                'Could not extract text from the uploaded PDF. '
                'Please ensure the file is not a scanned image-only PDF.'
            )

        result = '\n\n'.join(text_parts)
        print(f'[DEBUG]   PDFExtractor: ✅ total extracted: {len(result)} chars from {len(text_parts)} page(s)')
        return result
