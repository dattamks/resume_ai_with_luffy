"""
Abstract base class for all job source providers.

Each provider fetches job listings from an external API and returns a list
of DiscoveredJob-compatible dicts for deduplication and storage.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger('analyzer')


@dataclass
class RawJobListing:
    """
    Normalised job listing returned by any BaseJobSource implementation.
    Maps cleanly to the DiscoveredJob model fields.
    """
    source: str                                # 'firecrawl'
    external_id: str                           # Unique ID from the source API
    url: str                                   # Direct apply / listing URL
    title: str = ''
    company: str = ''
    location: str = ''
    salary_range: str = ''
    description_snippet: str = ''
    posted_at: Optional[str] = None            # ISO-8601 string or None
    raw_data: dict = field(default_factory=dict)
    source_page_url: str = ''                  # The search/career page URL we crawled

    # Enriched fields (extracted by LLM during crawl)
    skills_required: List[str] = field(default_factory=list)
    skills_nice_to_have: List[str] = field(default_factory=list)
    experience_years_min: Optional[int] = None
    experience_years_max: Optional[int] = None
    employment_type: str = ''                  # full_time, part_time, contract, internship, freelance
    remote_policy: str = ''                    # onsite, hybrid, remote
    seniority_level: str = ''                  # intern, junior, mid, senior, lead, manager, director, executive
    industry: str = ''                         # e.g. 'FinTech', 'Healthcare'
    education_required: str = ''               # e.g. 'bachelor', 'master', 'none'
    salary_min_usd: Optional[int] = None       # LLM-normalised annual USD
    salary_max_usd: Optional[int] = None       # LLM-normalised annual USD


class BaseJobSource(ABC):
    """
    Abstract base for all job source providers.

    Subclasses must implement `search()` which returns a list of
    RawJobListing objects given a set of search parameters.
    """

    @abstractmethod
    def search(
        self,
        queries: List[str],
        location: str = '',
        date_filter: str = 'month',
        max_results: int = 20,
    ) -> List[RawJobListing]:
        """
        Search for jobs matching the given queries.

        Args:
            queries: List of search strings (e.g. ['Python developer', 'Django engineer'])
            location: Geographic location filter (e.g. 'London, UK')
            date_filter: Recency filter ('day', 'week', 'month')
            max_results: Maximum number of results per query

        Returns:
            List of RawJobListing objects (may be empty on failure)
        """
        raise NotImplementedError

    def name(self) -> str:
        """Human-readable name of this source."""
        return self.__class__.__name__
