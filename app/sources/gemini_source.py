"""Google Gemini news source parser."""

import hashlib
import logging
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from .base import Article, BaseSource

logger = logging.getLogger(__name__)

# Common headers to avoid being blocked
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

TIMEOUT = 10  # seconds


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

        return articles[:limit]

    def _fetch_from_changelog(self, limit: int) -> list[Article]:
        """Fetch updates from the Gemini API changelog.

        Args:
            limit: Maximum number of entries to fetch.

        Returns:
            List of Article objects representing changelog entries.
        """
        response = requests.get(self.CHANGELOG_URL, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()

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
        """Fetch Gemini-related articles from Google AI Blog.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        response = requests.get(self.AI_BLOG_URL, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()

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

    @staticmethod
    def _build_changelog_title(date_title: str, content: str) -> str:
        """Build a descriptive title for changelog entries.

        Changelog entries often have just a date as the heading.
        This prepends 'Gemini API Changelog:' and appends a short
        content hint to make the title more informative.

        Args:
            date_title: The raw date heading text.
            content: The changelog entry content.

        Returns:
            A descriptive title string.
        """
        # Extract first meaningful line as a hint (up to 60 chars)
        hint = ""
        for line in content.split("\n"):
            line = line.strip()
            if line and len(line) > 10:
                hint = line[:60].rstrip()
                if len(line) > 60:
                    hint += "..."
                break

        if hint:
            return f"Gemini API Changelog: {date_title} - {hint}"
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

        Creates an anchor that combines the slugified title with a short hash
        of the content to ensure uniqueness even for entries with similar titles.

        Args:
            title: The entry title.
            content: The entry content.
            published_at: The publication date (if available).

        Returns:
            A unique anchor string suitable for URL fragments.
        """
        # Start with slugified title
        slug = self._slugify(title)

        # Add date component if available
        date_part = ""
        if published_at:
            date_part = published_at.strftime("%Y%m%d")

        # Create a short hash from content for uniqueness
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]

        # Combine components
        if date_part:
            return f"{slug}-{date_part}-{content_hash}"
        return f"{slug}-{content_hash}"
