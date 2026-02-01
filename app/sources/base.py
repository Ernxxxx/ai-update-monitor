"""Base class for all news sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Article:
    """Represents a news article from an AI company."""

    url: str
    title: str
    content: str
    source: str  # "openai", "anthropic", "gemini"
    published_at: datetime | None = None


class BaseSource(ABC):
    """Abstract base class for news sources."""

    name: str  # Source name identifier

    @abstractmethod
    def fetch_articles(self, limit: int = 10) -> list[Article]:
        """Fetch the latest N articles from the source.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects. Returns empty list on failure.
        """
        pass
