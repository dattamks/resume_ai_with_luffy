import requests
from bs4 import BeautifulSoup


class JDFetcher:
    """Fetches and cleans job description content from a URL."""

    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }
    TIMEOUT = 10

    def fetch(self, url: str) -> str:
        """
        Fetch the page at `url` and return cleaned visible text.
        Raises ValueError on fetch failure or if no content is found.
        """
        try:
            response = requests.get(url, headers=self.HEADERS, timeout=self.TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ValueError(f'Failed to fetch job description URL: {exc}') from exc

        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script/style noise
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()

        text = soup.get_text(separator='\n')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned = '\n'.join(lines)

        if not cleaned:
            raise ValueError('No readable content found at the provided URL.')

        return cleaned

    def build_from_form(
        self,
        role: str = '',
        company: str = '',
        skills: str = '',
        experience_years: int = None,
        industry: str = '',
        extra_details: str = '',
    ) -> str:
        """
        Assemble a human-readable job description string from structured form fields.
        """
        parts = []

        if role:
            parts.append(f'Job Title: {role}')
        if company:
            parts.append(f'Company: {company}')
        if industry:
            parts.append(f'Industry: {industry}')
        if experience_years is not None:
            parts.append(f'Required Experience: {experience_years} year(s)')
        if skills:
            parts.append(f'Required Skills / Technologies: {skills}')
        if extra_details:
            parts.append(f'Additional Details:\n{extra_details}')

        if not parts:
            raise ValueError('At least one job description field must be provided.')

        return '\n'.join(parts)
