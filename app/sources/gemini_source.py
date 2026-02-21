"""Google Gemini news source parser."""

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from .base import Article, BaseSource
from .http_client import fetch_with_retry, RSS_HEADERS, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

TIMEOUT = DEFAULT_TIMEOUT

# RSS feeds for sources that support them
AI_BLOG_RSS = "https://blog.google/technology/ai/rss/"
DEEPMIND_RSS = "https://deepmind.google/blog/rss.xml"


class GeminiSource(BaseSource):
    """Parser for Google Gemini official sources."""

    name = "gemini"

    # TODO: Google may change their URL structure. Monitor these URLs:
    # - https://ai.google.dev/gemini-api/docs/changelog (API changelog)
    # - https://blog.google/technology/ai/ (Google AI Blog - general)
    # - https://developers.googleblog.com/ (Developers Blog)
    CHANGELOG_URL = "https://ai.google.dev/gemini-api/docs/changelog"
    AI_BLOG_URL = "https://blog.google/technology/ai/"

    def fetch_articles(self, limit: int = 10) -> list[Article]:
        """Fetch the latest articles/updates from Gemini sources.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects. Returns empty list on failure.
        """
        articles: list[Article] = []
        seen_keys: set[str] = set()  # Track unique articles by URL+title

        # Try changelog first (most relevant for API updates)
        try:
            changelog_articles = self._fetch_from_changelog(limit)
            for article in changelog_articles:
                unique_key = self._generate_unique_key(article.url, article.title)
                if unique_key not in seen_keys:
                    seen_keys.add(unique_key)
                    articles.append(article)
        except Exception as e:
            logger.error(f"Failed to fetch from Gemini changelog: {e}")

        # If we don't have enough, try the AI blog
        if len(articles) < limit:
            try:
                remaining = limit - len(articles)
                blog_articles = self._fetch_from_ai_blog(remaining)
                for article in blog_articles:
                    unique_key = self._generate_unique_key(article.url, article.title)
                    if unique_key not in seen_keys:
                        seen_keys.add(unique_key)
                        articles.append(article)
            except Exception as e:
                logger.error(f"Failed to fetch from Google AI blog: {e}")

        # Also fetch from DeepMind blog RSS
        if len(articles) < limit:
            try:
                remaining = limit - len(articles)
                deepmind_articles = self._fetch_from_deepmind(remaining)
                for article in deepmind_articles:
                    unique_key = self._generate_unique_key(article.url, article.title)
                    if unique_key not in seen_keys:
                        seen_keys.add(unique_key)
                        articles.append(article)
            except Exception as e:
                logger.error(f"Failed to fetch from DeepMind blog: {e}")

        return articles[:limit]

    def _fetch_from_changelog(self, limit: int) -> list[Article]:
        """Fetch updates from the Gemini API changelog.

        Args:
            limit: Maximum number of entries to fetch.

        Returns:
            List of Article objects representing changelog entries.
        """
        response = fetch_with_retry(self.CHANGELOG_URL, timeout=TIMEOUT)

        soup = BeautifulSoup(response.text, "html.parser")
        articles: list[Article] = []
        seen_keys: set[str] = set()  # Track unique articles

        # Page structure: <h2>Date</h2> followed by <ul><li>...</li></ul>
        # Each h2 is a date heading, the next sibling ul contains the updates
        h2_elements = soup.select("h2")

        for h2 in h2_elements:
            if len(articles) >= limit:
                break

            text = h2.get_text(strip=True)
            parsed_date = self._parse_changelog_date(text)

            if not parsed_date:
                continue

            # Skip entries older than 30 days
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            entry_date = parsed_date if parsed_date.tzinfo else parsed_date.replace(tzinfo=timezone.utc)
            if entry_date < cutoff:
                continue

            # Collect all ul > li content following this h2 until next h2
            content_parts: list[str] = []
            sibling = h2.find_next_sibling()
            while sibling and sibling.name != "h2":
                if sibling.name == "ul":
                    for li in sibling.find_all("li", recursive=False):
                        li_text = li.get_text(strip=True)
                        if li_text:
                            content_parts.append(f"- {li_text}")
                sibling = sibling.find_next_sibling()

            if not content_parts:
                continue

            content = "\n".join(content_parts)
            display_title = self._build_changelog_title(text, content)
            unique_anchor = self._generate_unique_anchor(text, content, parsed_date)
            url = f"{self.CHANGELOG_URL}#{unique_anchor}"

            unique_key = self._generate_unique_key(url, text)
            if unique_key not in seen_keys:
                seen_keys.add(unique_key)
                articles.append(
                    Article(
                        url=url,
                        title=display_title,
                        content=content,
                        source=self.name,
                        published_at=parsed_date,
                    )
                )

        # Alternative approach if h2 method found nothing
        if not articles:
            articles = self._fetch_changelog_alternative(soup, limit)

        return articles

    def _fetch_changelog_alternative(self, soup: BeautifulSoup, limit: int) -> list[Article]:
        """Alternative method to parse changelog if primary method fails.

        Args:
            soup: BeautifulSoup object of the changelog page.
            limit: Maximum number of entries to fetch.

        Returns:
            List of Article objects.
        """
        articles: list[Article] = []
        seen_keys: set[str] = set()

        # TODO: Update based on actual page structure
        # Try finding changelog entries in different structures
        entries = soup.select("article, .changelog-entry, .release-notes-entry, section")

        for entry in entries[:limit]:
            title_elem = entry.select_one("h2, h3, h4, .title")
            if not title_elem:
                continue

            title = title_elem.get_text(strip=True)
            if not title:
                continue

            # Get content
            content_parts = []
            for p in entry.select("p, li"):
                text = p.get_text(strip=True)
                if text:
                    content_parts.append(text)

            content = "\n".join(content_parts)

            # Try to extract date
            published_at = self._extract_date_from_element(entry)
            if not published_at:
                published_at = self._parse_changelog_date(title)

            # Generate unique URL with anchor based on title and content
            unique_anchor = self._generate_unique_anchor(title, content, published_at)
            url = f"{self.CHANGELOG_URL}#{unique_anchor}"

            # Check for duplicates
            unique_key = self._generate_unique_key(url, title)
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)

            articles.append(
                Article(
                    url=url,
                    title=title,
                    content=content,
                    source=self.name,
                    published_at=published_at,
                )
            )

        return articles

    def _fetch_from_ai_blog(self, limit: int) -> list[Article]:
        """Fetch articles from Google AI Blog.

        Tries RSS feed first for stability, falls back to HTML scraping.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        # Try RSS first (more stable than scraping)
        try:
            articles = self._fetch_from_rss(AI_BLOG_RSS, limit, "Google AI Blog")
            if articles:
                return articles
        except Exception as e:
            logger.debug(f"Google AI Blog RSS failed, falling back to scraping: {e}")

        # Fall back to HTML scraping
        response = fetch_with_retry(self.AI_BLOG_URL, timeout=TIMEOUT)

        soup = BeautifulSoup(response.text, "html.parser")
        articles: list[Article] = []

        # TODO: Update selectors based on actual Google Blog structure
        # The blog uses various card layouts
        article_cards = soup.select(
            "article, .post-card, .article-card, [data-testid='article']"
        )

        if not article_cards:
            # Fallback: look for links to articles
            article_cards = soup.select("a[href*='/technology/ai/']")

        seen_urls: set[str] = set()
        for card in article_cards:
            if len(articles) >= limit:
                break

            # Find link
            if card.name == "a":
                link = card
            else:
                link = card.select_one("a[href]")

            if not link:
                continue

            href = link.get("href", "")
            if not href or href in seen_urls:
                continue

            # Filter for Gemini-related content
            # TODO: Improve filtering logic based on actual content patterns
            card_text = card.get_text().lower()
            if "gemini" not in card_text and "gemini" not in href.lower():
                continue

            # Build full URL
            if href.startswith("/"):
                url = f"https://blog.google{href}"
            elif href.startswith("http"):
                url = href
            else:
                continue

            seen_urls.add(href)

            # Extract title
            title_elem = card.select_one("h1, h2, h3, h4, .title, .headline")
            title = title_elem.get_text(strip=True) if title_elem else link.get_text(strip=True)

            if not title or len(title) < 5:
                continue

            # Extract date
            published_at = self._extract_date_from_element(card)

            # Extract summary
            summary_elem = card.select_one("p, .summary, .excerpt")
            content = summary_elem.get_text(strip=True) if summary_elem else ""

            articles.append(
                Article(
                    url=url,
                    title=title,
                    content=content,
                    source=self.name,
                    published_at=published_at,
                )
            )

        return articles

    def _fetch_from_rss(self, feed_url: str, limit: int, label: str = "") -> list[Article]:
        """Fetch articles from an RSS feed using feedparser.

        Args:
            feed_url: URL of the RSS feed.
            limit: Maximum number of articles to fetch.
            label: Label for logging.

        Returns:
            List of Article objects.
        """
        logger.info(f"Trying RSS feed: {feed_url}")
        resp = fetch_with_retry(feed_url, headers=RSS_HEADERS, timeout=TIMEOUT)
        feed = feedparser.parse(resp.text)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Failed to parse RSS feed: {feed.bozo_exception}")

        articles: list[Article] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)

        for entry in feed.entries[:limit]:
            try:
                url = entry.get("link", "")
                if not url:
                    continue

                title = entry.get("title", "").strip()
                if not title:
                    continue

                # Extract content
                content = ""
                if "content" in entry and entry.content:
                    content = entry.content[0].get("value", "")
                elif "summary" in entry:
                    content = entry.get("summary", "")

                # Strip HTML tags from content
                if content:
                    content = BeautifulSoup(content, "html.parser").get_text(
                        separator="\n", strip=True
                    )

                # Extract date
                published_at = None
                for field in ("published_parsed", "updated_parsed"):
                    parsed = entry.get(field)
                    if parsed:
                        try:
                            published_at = datetime(*parsed[:6], tzinfo=timezone.utc)
                            break
                        except (TypeError, ValueError):
                            continue

                # Skip old articles
                if published_at and published_at < cutoff:
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
                logger.debug(f"Failed to parse RSS entry: {e}")
                continue

        if label:
            logger.info(f"Found {len(articles)} articles from {label} RSS")
        return articles

    def _fetch_from_deepmind(self, limit: int) -> list[Article]:
        """Fetch articles from Google DeepMind blog via RSS.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        return self._fetch_from_rss(DEEPMIND_RSS, limit, "DeepMind")

    @staticmethod
    def _build_changelog_title(date_title: str, content: str) -> str:
        """Build a stable title for changelog entries.

        Uses only the date to ensure title stability across runs.
        Content changes on the changelog page won't cause re-posting.

        Args:
            date_title: The raw date heading text.
            content: The changelog entry content (unused, kept for API compat).

        Returns:
            A stable title string.
        """
        return f"Gemini API Changelog: {date_title}"

    def _parse_changelog_date(self, text: str) -> datetime | None:
        """Parse date from changelog heading text.

        Args:
            text: Text that may contain a date.

        Returns:
            datetime object if parsed successfully, None otherwise.
        """
        # TODO: Add more date patterns based on actual changelog format
        # Common patterns: "January 15, 2024", "2024-01-15", "Jan 15, 2024"

        patterns = [
            (r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", "%B %d %Y"),      # January 15, 2024
            (r"(\d{4})-(\d{2})-(\d{2})", None),                   # 2024-01-15 (ISO)
            (r"(\d{1,2})\s+(\w+)\s+(\d{4})", "%d %B %Y"),        # 15 January 2024
        ]

        for pattern, date_format in patterns:
            match = re.search(pattern, text)
            if match:
                if date_format is None:
                    # ISO format
                    try:
                        return datetime.fromisoformat(match.group(0))
                    except ValueError:
                        continue
                else:
                    try:
                        date_str = " ".join(match.groups())
                        return datetime.strptime(date_str, date_format)
                    except ValueError:
                        continue

        return None

    def _extract_date_from_element(self, element: BeautifulSoup) -> datetime | None:
        """Extract date from an element.

        Args:
            element: BeautifulSoup element to search.

        Returns:
            datetime object if found, None otherwise.
        """
        # Try <time> element
        time_elem = element.select_one("time[datetime]")
        if time_elem:
            try:
                date_str = time_elem.get("datetime", "")
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Try date classes
        date_elem = element.select_one(".date, .published, .post-date")
        if date_elem:
            return self._parse_changelog_date(date_elem.get_text())

        return None

    def _slugify(self, text: str) -> str:
        """Convert text to URL-friendly slug.

        Args:
            text: Text to slugify.

        Returns:
            URL-friendly slug string.
        """
        # Remove non-alphanumeric characters and convert to lowercase
        slug = re.sub(r"[^\w\s-]", "", text.lower())
        slug = re.sub(r"[-\s]+", "-", slug).strip("-")
        return slug

    def _generate_unique_key(self, url: str, title: str) -> str:
        """Generate a unique key for deduplication based on URL and title.

        Args:
            url: The article URL.
            title: The article title.

        Returns:
            A unique key string for identifying the article.
        """
        # Normalize title for comparison (lowercase, strip whitespace)
        normalized_title = title.lower().strip()
        # Create a combined key
        combined = f"{url}|{normalized_title}"
        return hashlib.md5(combined.encode("utf-8")).hexdigest()

    def _generate_unique_anchor(
        self, title: str, content: str, published_at: datetime | None
    ) -> str:
        """Generate a unique anchor for changelog entries.

        Creates an anchor that combines the slugified title with the date.
        Using only date (no content hash) ensures the same changelog date
        always produces the same URL, preventing duplicate posts when
        content changes slightly.

        Args:
            title: The entry title.
            content: The entry content (unused, kept for API compatibility).
            published_at: The publication date (if available).

        Returns:
            A unique anchor string suitable for URL fragments.
        """
        slug = self._slugify(title)
        if published_at:
            date_part = published_at.strftime("%Y%m%d")
            return f"{slug}-{date_part}"
        return slug
