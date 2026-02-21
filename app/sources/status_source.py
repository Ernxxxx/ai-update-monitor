"""Status page monitoring source for AI service providers.

Monitors RSS/Atom feeds from OpenAI, Anthropic, and Google Cloud status pages
to provide real-time incident notifications.
"""

import logging
from datetime import datetime, timedelta, timezone

import feedparser
from bs4 import BeautifulSoup

from .base import Article, BaseSource
from .http_client import fetch_with_retry, RSS_HEADERS, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

TIMEOUT = DEFAULT_TIMEOUT


class StatusSource(BaseSource):
    """Monitor status pages of major AI providers via RSS/Atom feeds."""

    name = "status"

    FEEDS = [
        ("OpenAI", "https://status.openai.com/feed.rss"),
        ("Anthropic", "https://status.claude.com/history.rss"),
        ("Google Cloud", "https://status.cloud.google.com/en/feed.atom"),
    ]

    def fetch_articles(self, limit: int = 10) -> list[Article]:
        """Fetch recent status incidents from all providers.

        Args:
            limit: Maximum number of incidents to fetch.

        Returns:
            List of Article objects representing status incidents.
        """
        articles: list[Article] = []
        seen_urls: set[str] = set()

        for provider_name, feed_url in self.FEEDS:
            try:
                new_articles = self._fetch_feed(provider_name, feed_url, limit)
                for article in new_articles:
                    if article.url not in seen_urls:
                        seen_urls.add(article.url)
                        articles.append(article)
            except Exception as e:
                logger.error(f"Failed to fetch status feed for {provider_name}: {e}")

        # Sort by date (newest first)
        articles.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        return articles[:limit]

    def _fetch_feed(
        self, provider_name: str, feed_url: str, limit: int
    ) -> list[Article]:
        """Fetch and parse a single status RSS/Atom feed.

        Args:
            provider_name: Display name of the provider.
            feed_url: URL of the RSS/Atom feed.
            limit: Maximum number of entries to fetch.

        Returns:
            List of Article objects.
        """
        logger.info(f"Fetching status feed: {provider_name} ({feed_url})")
        resp = fetch_with_retry(feed_url, headers=RSS_HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(resp.text)

        if feed.bozo and not feed.entries:
            raise ValueError(
                f"Failed to parse status feed for {provider_name}: {feed.bozo_exception}"
            )

        articles: list[Article] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        for entry in feed.entries[:limit]:
            try:
                url = entry.get("link", "")
                if not url:
                    continue

                title = entry.get("title", "").strip()
                if not title:
                    continue

                # Prefix with provider name for clarity in shared channel
                title = f"[{provider_name}] {title}"

                # Extract content/description
                content = ""
                if "content" in entry and entry.content:
                    content = entry.content[0].get("value", "")
                elif "summary" in entry:
                    content = entry.get("summary", "")
                elif "description" in entry:
                    content = entry.get("description", "")

                # Strip HTML tags from content
                if content:
                    content = BeautifulSoup(content, "html.parser").get_text(
                        separator="\n", strip=True
                    )

                # Extract publication date
                published_at = self._parse_feed_date(entry)

                # Skip incidents older than 7 days
                if published_at:
                    pub_aware = (
                        published_at
                        if published_at.tzinfo
                        else published_at.replace(tzinfo=timezone.utc)
                    )
                    if pub_aware < cutoff:
                        continue

                articles.append(
                    Article(
                        url=url,
                        title=title,
                        content=content,
                        source=self.name,
                        published_at=published_at,
                    )
                )
            except Exception as e:
                logger.debug(f"Failed to parse status entry: {e}")
                continue

        logger.info(f"Found {len(articles)} status incidents from {provider_name}")
        return articles

    @staticmethod
    def _parse_feed_date(entry) -> datetime | None:
        """Extract publication date from a feed entry.

        Args:
            entry: feedparser entry object.

        Returns:
            datetime object if parsed, None otherwise.
        """
        for field in ("published_parsed", "updated_parsed"):
            parsed = entry.get(field)
            if parsed:
                try:
                    return datetime(*parsed[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    continue
        return None
