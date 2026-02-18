"""Anthropic news source parser."""

import logging
import re
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .base import Article, BaseSource
from .http_client import create_session, fetch_with_retry, RSS_HEADERS, DEFAULT_TIMEOUT
from .playwright_base import PlaywrightMixin, fetch_with_playwright

logger = logging.getLogger(__name__)

TIMEOUT = DEFAULT_TIMEOUT


class AnthropicSource(BaseSource, PlaywrightMixin):
    """Parser for Anthropic official news sources."""

    name = "anthropic"

    NEWS_URL = "https://www.anthropic.com/news"

    # Anthropic does not currently provide an RSS feed.
    # Keep only the most likely candidates to minimize timeout overhead.
    RSS_URLS = [
        "https://www.anthropic.com/feed.xml",
        "https://www.anthropic.com/rss.xml",
    ]

    def __init__(self):
        """Initialize the source with a session."""
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        """Get or create a requests session."""
        if self._session is None:
            self._session = create_session()
        return self._session

    def fetch_articles(self, limit: int = 10) -> list[Article]:
        """Fetch the latest articles from Anthropic news.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects. Returns empty list on failure.
        """
        # Try RSS feed first (most reliable if available)
        articles = self._try_rss_feeds(limit)
        if articles:
            logger.info(f"Fetched {len(articles)} articles from Anthropic RSS")
            return articles

        # Fall back to HTML scraping
        try:
            articles = self._fetch_from_news_page(limit)
            if articles:
                logger.info(f"Fetched {len(articles)} articles from Anthropic news page")
                return articles
        except requests.RequestException as e:
            logger.error(f"Network error fetching Anthropic news: {e}")
        except Exception as e:
            logger.error(f"Failed to fetch from Anthropic news page: {e}")

        # Fall back to Playwright for bot protection bypass
        logger.info("Falling back to Playwright for Anthropic news")
        try:
            articles = self._fetch_with_playwright(limit)
            if articles:
                logger.info(f"Fetched {len(articles)} articles from Anthropic using Playwright")
                return articles
        except Exception as e:
            logger.error(f"Playwright fetch failed for Anthropic: {e}")

        return []

    def _try_rss_feeds(self, limit: int) -> list[Article]:
        """Try to fetch articles from RSS feeds.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects, or empty list if all feeds fail.
        """
        session = self._get_session()

        for rss_url in self.RSS_URLS:
            try:
                response = fetch_with_retry(
                    rss_url,
                    session=session,
                    headers=RSS_HEADERS,
                    timeout=TIMEOUT,
                    max_retries=1,  # Don't waste time retrying RSS that likely 404s
                )

                if response.status_code == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "xml" in content_type or response.text.strip().startswith("<?xml"):
                        articles = self._parse_rss(response.text, limit)
                        if articles:
                            logger.debug(f"Successfully parsed RSS from {rss_url}")
                            return articles
            except requests.RequestException as e:
                logger.debug(f"Failed to fetch RSS from {rss_url}: {e}")
                continue
            except Exception as e:
                logger.debug(f"Error parsing RSS from {rss_url}: {e}")
                continue

        return []

    def _parse_rss(self, xml_content: str, limit: int) -> list[Article]:
        """Parse RSS/Atom feed content.

        Args:
            xml_content: XML content string.
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        articles: list[Article] = []

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            logger.debug(f"RSS parse error: {e}")
            return []

        # Handle both RSS 2.0 and Atom feeds
        namespaces = {
            "atom": "http://www.w3.org/2005/Atom",
            "content": "http://purl.org/rss/1.0/modules/content/",
        }

        # Try RSS 2.0 format
        items = root.findall(".//item")

        # Try Atom format if no RSS items found
        if not items:
            items = root.findall(".//atom:entry", namespaces)
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items[:limit]:
            url = self._get_rss_link(item, namespaces)
            title = self._get_rss_text(item, ["title"], namespaces)

            if not url or not title:
                continue

            content = self._get_rss_text(
                item,
                ["content:encoded", "content", "description", "summary"],
                namespaces
            )

            published_at = self._get_rss_date(item, namespaces)

            # Skip articles older than 14 days
            if published_at:
                from datetime import timezone, timedelta
                cutoff = datetime.now(timezone.utc) - timedelta(days=14)
                pub_aware = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
                if pub_aware < cutoff:
                    continue

            articles.append(
                Article(
                    url=url,
                    title=title,
                    content=content or "",
                    source=self.name,
                    published_at=published_at,
                )
            )

        return articles

    def _get_rss_link(self, item: ElementTree.Element, namespaces: dict) -> str:
        """Extract link from RSS/Atom item."""
        # RSS 2.0
        link_elem = item.find("link")
        if link_elem is not None and link_elem.text:
            return link_elem.text.strip()

        # Atom
        for link in item.findall("atom:link", namespaces) + item.findall("{http://www.w3.org/2005/Atom}link"):
            href = link.get("href")
            if href:
                rel = link.get("rel", "alternate")
                if rel == "alternate" or not link.get("rel"):
                    return href

        return ""

    def _get_rss_text(self, item: ElementTree.Element, tag_names: list[str], namespaces: dict) -> str:
        """Extract text from RSS/Atom item, trying multiple tag names."""
        for tag in tag_names:
            # Try direct find
            elem = item.find(tag)
            if elem is not None and elem.text:
                return elem.text.strip()

            # Try with namespaces
            for ns_prefix, ns_uri in namespaces.items():
                elem = item.find(f"{{{ns_uri}}}{tag}")
                if elem is not None and elem.text:
                    return elem.text.strip()
                elem = item.find(f"{ns_prefix}:{tag}", namespaces)
                if elem is not None and elem.text:
                    return elem.text.strip()

        return ""

    def _get_rss_date(self, item: ElementTree.Element, namespaces: dict) -> datetime | None:
        """Extract publication date from RSS/Atom item."""
        date_tags = ["pubDate", "published", "updated", "date", "dc:date"]

        for tag in date_tags:
            elem = item.find(tag)
            if elem is None:
                for ns_prefix, ns_uri in namespaces.items():
                    elem = item.find(f"{{{ns_uri}}}{tag}")
                    if elem is not None:
                        break
                    elem = item.find(f"{ns_prefix}:{tag}", namespaces)
                    if elem is not None:
                        break

            if elem is not None and elem.text:
                parsed = self._parse_rss_date(elem.text.strip())
                if parsed:
                    return parsed

        return None

    def _parse_rss_date(self, date_str: str) -> datetime | None:
        """Parse date from RSS format."""
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",      # RSS 2.0: Sat, 15 Jan 2024 12:00:00 +0000
            "%a, %d %b %Y %H:%M:%S %Z",      # With timezone name
            "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601
            "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 with Z
            "%Y-%m-%d",                       # Simple date
        ]

        # Handle timezone suffix variations
        date_str = date_str.replace("Z", "+00:00")

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Try fromisoformat as fallback
        try:
            return datetime.fromisoformat(date_str)
        except ValueError:
            pass

        return None

    def _fetch_from_news_page(self, limit: int) -> list[Article]:
        """Fetch articles from the news page via HTML scraping.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        session = self._get_session()
        response = fetch_with_retry(self.NEWS_URL, session=session, timeout=TIMEOUT)

        soup = BeautifulSoup(response.text, "html.parser")
        articles: list[Article] = []

        # Try multiple selector strategies
        article_elements = self._find_article_elements(soup)

        if not article_elements:
            logger.warning("No article elements found on Anthropic news page")
            return []

        seen_urls: set[str] = set()
        for elem in article_elements:
            if len(articles) >= limit:
                break

            article = self._parse_article_element(elem, seen_urls)
            if article:
                articles.append(article)
                seen_urls.add(article.url)

        return articles

    def _fetch_article_content(self, url: str) -> str:
        """Fetch full article content from the article page.

        Args:
            url: The article URL to fetch content from.

        Returns:
            Article content text (max 3000 characters), or empty string on failure.
        """
        try:
            # Use domcontentloaded with longer extra_wait (networkidle often times out)
            html_content = fetch_with_playwright(
                url,
                wait_selector='article, .post-content, main, .content, [class*="article"]',
                timeout=30000,
                wait_until="domcontentloaded",
                extra_wait=5000,  # 5 seconds for JS to render content
            )

            soup = BeautifulSoup(html_content, "html.parser")

            # Try multiple selectors to find the article body
            content_selectors = [
                'article',
                '.post-content',
                '[class*="post-content"]',
                '[class*="article-content"]',
                '[class*="article-body"]',
                '[class*="entry-content"]',
                '.content',
                '[class*="content"]',
                'main',
                '[role="main"]',
            ]

            content_text = ""
            for selector in content_selectors:
                try:
                    content_elem = soup.select_one(selector)
                    if content_elem:
                        # Remove script, style, nav, header, footer elements
                        for tag in content_elem.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                            tag.decompose()

                        # Get text content
                        text = content_elem.get_text(separator='\n', strip=True)
                        if text and len(text) > 100:  # Minimum reasonable content length
                            content_text = text
                            break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue

            # Limit to 3000 characters
            if len(content_text) > 3000:
                content_text = content_text[:3000] + "..."

            return content_text

        except Exception as e:
            logger.warning(f"Failed to fetch article content from {url}: {e}")
            return ""

    def _fetch_with_playwright(self, limit: int) -> list[Article]:
        """Fetch articles using Playwright for bot protection bypass.

        Uses listing page only - does NOT fetch individual article content
        to avoid 2+ minute delays from per-article Playwright loads.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        try:
            html_content = fetch_with_playwright(
                self.NEWS_URL,
                wait_selector='a[href*="/news/"]',
                timeout=30000,
                extra_wait=2000,
            )

            soup = BeautifulSoup(html_content, "html.parser")
            articles: list[Article] = []

            article_elements = self._find_article_elements(soup)

            if not article_elements:
                logger.warning("No article elements found with Playwright")
                return []

            seen_urls: set[str] = set()
            for elem in article_elements:
                if len(articles) >= limit:
                    break

                article = self._parse_article_element(elem, seen_urls)
                if article:
                    articles.append(article)
                    seen_urls.add(article.url)

            return articles
        except Exception as e:
            logger.error(f"Playwright fetch error: {e}")
            raise

    def _find_article_elements(self, soup: BeautifulSoup) -> list:
        """Find article elements using multiple selector strategies.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            List of article elements.
        """
        # Strategy 1: Links with /news/ in href (most reliable)
        selectors = [
            # Direct news links
            'a[href*="/news/"]',
            # Common article containers
            'article a[href]',
            '[class*="post"] a[href]',
            '[class*="article"] a[href]',
            '[class*="news"] a[href]',
            '[class*="card"] a[href]',
            '[class*="item"] a[href]',
            # Grid/list containers
            '[class*="grid"] a[href*="/news"]',
            '[class*="list"] a[href*="/news"]',
            # Data attributes
            '[data-testid*="news"] a[href]',
            '[data-testid*="article"] a[href]',
            '[data-testid*="post"] a[href]',
            # Broader patterns
            'main a[href*="/news/"]',
            'section a[href*="/news/"]',
            '.container a[href*="/news/"]',
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)
                # Filter to only news article links
                filtered = []
                for elem in elements:
                    href = elem.get("href", "")
                    # Must be a specific news article, not just /news or /news/
                    if href and "/news/" in href and href not in ["/news", "/news/"]:
                        # Check if it looks like an article path
                        path_parts = href.rstrip("/").split("/")
                        if len(path_parts) > 2:  # Has slug after /news/
                            filtered.append(elem)

                if filtered:
                    logger.debug(f"Found {len(filtered)} articles with selector: {selector}")
                    return filtered
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue

        # Strategy 2: Find parent containers that hold multiple article links
        containers = soup.select('main, [role="main"], .content, #content, section')
        for container in containers:
            links = container.find_all("a", href=re.compile(r"/news/[^/]+"))
            if links:
                logger.debug(f"Found {len(links)} articles in container")
                return links

        # Strategy 3: Look for any links with news in path
        all_links = soup.find_all("a", href=True)
        news_links = []
        for link in all_links:
            href = link.get("href", "")
            if "/news/" in href and href not in ["/news", "/news/"]:
                path_parts = href.rstrip("/").split("/")
                if len(path_parts) > 2:
                    news_links.append(link)

        if news_links:
            logger.debug(f"Found {len(news_links)} news links from all links")
            return news_links

        return []

    def _parse_article_element(self, elem: BeautifulSoup, seen_urls: set[str]) -> Article | None:
        """Parse a single article element.

        Args:
            elem: BeautifulSoup element.
            seen_urls: Set of already processed URLs.

        Returns:
            Article object or None if parsing fails.
        """
        # Get the link
        if elem.name == "a":
            link = elem
        else:
            link = elem.select_one("a[href]")

        if not link:
            return None

        href = link.get("href", "")
        if not href:
            return None

        # Build full URL
        if href.startswith("/"):
            url = f"https://www.anthropic.com{href}"
        elif href.startswith("http"):
            url = href
        else:
            return None

        # Skip duplicates
        if url in seen_urls or href in seen_urls:
            return None

        # Skip non-article pages
        if href in ["/news", "/news/"] or url.endswith("/news") or url.endswith("/news/"):
            return None

        # Extract title - look in parent elements too
        title = self._extract_title_enhanced(elem, link)
        if not title:
            return None

        # Extract date - look in parent elements too
        published_at = self._extract_date_enhanced(elem)

        # Extract summary
        content = self._extract_summary_enhanced(elem)

        return Article(
            url=url,
            title=title,
            content=content,
            source=self.name,
            published_at=published_at,
        )

    def _extract_title_enhanced(self, elem: BeautifulSoup, link: BeautifulSoup) -> str:
        """Extract article title with enhanced search.

        Args:
            elem: The article element.
            link: The link element.

        Returns:
            Title string, or empty string if not found.
        """
        # Get parent elements to search
        parents = [elem]
        parent = elem.parent
        for _ in range(5):  # Look up to 5 levels up
            if parent and parent.name not in ["body", "html", "[document]"]:
                parents.append(parent)
                parent = parent.parent
            else:
                break

        # Search for title in element and parents
        for container in parents:
            # Heading elements
            for heading in ["h1", "h2", "h3", "h4"]:
                title_elem = container.select_one(heading)
                if title_elem:
                    text = title_elem.get_text(strip=True)
                    if text and len(text) > 5:  # Reasonable title length
                        return text

            # Title classes
            title_selectors = [
                '[class*="title"]',
                '[class*="headline"]',
                '[class*="heading"]',
                '[data-testid*="title"]',
            ]
            for selector in title_selectors:
                try:
                    title_elem = container.select_one(selector)
                    if title_elem:
                        text = title_elem.get_text(strip=True)
                        if text and len(text) > 5:
                            return text
                except Exception:
                    continue

        # Fall back to link text
        link_text = link.get_text(strip=True)
        if link_text and len(link_text) > 5:
            return link_text

        # Try aria-label or title attribute
        for attr in ["aria-label", "title"]:
            attr_val = link.get(attr)
            if attr_val and len(attr_val) > 5:
                return attr_val

        return ""

    def _extract_date_enhanced(self, elem: BeautifulSoup) -> datetime | None:
        """Extract publication date with enhanced search.

        Args:
            elem: The article element.

        Returns:
            datetime object if found, None otherwise.
        """
        # Get parent elements
        elements_to_search = [elem]
        parent = elem.parent
        for _ in range(5):
            if parent and parent.name not in ["body", "html", "[document]"]:
                elements_to_search.append(parent)
                parent = parent.parent
            else:
                break

        for container in elements_to_search:
            # <time> element with datetime attribute
            time_elem = container.select_one("time[datetime]")
            if time_elem:
                try:
                    date_str = time_elem.get("datetime", "")
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Date classes
            date_selectors = [
                '[class*="date"]',
                '[class*="time"]',
                '[class*="published"]',
                '[data-testid*="date"]',
                'time',
            ]
            for selector in date_selectors:
                try:
                    date_elem = container.select_one(selector)
                    if date_elem:
                        date_text = date_elem.get_text(strip=True)
                        parsed = self._parse_date_text(date_text)
                        if parsed:
                            return parsed
                except Exception:
                    continue

        return None

    def _parse_date_text(self, date_text: str) -> datetime | None:
        """Parse date from text in various formats.

        Args:
            date_text: Date string to parse.

        Returns:
            datetime object if parsed successfully, None otherwise.
        """
        if not date_text:
            return None

        # Clean up the text
        date_text = date_text.strip()

        formats = [
            "%B %d, %Y",      # January 15, 2024
            "%b %d, %Y",      # Jan 15, 2024
            "%Y-%m-%d",       # 2024-01-15
            "%d %B %Y",       # 15 January 2024
            "%d %b %Y",       # 15 Jan 2024
            "%m/%d/%Y",       # 01/15/2024
            "%d/%m/%Y",       # 15/01/2024
            "%B %Y",          # January 2024
            "%b %Y",          # Jan 2024
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_text, fmt)
            except ValueError:
                continue

        # Try to extract date pattern with regex
        patterns = [
            (r"(\w+ \d{1,2}, \d{4})", "%B %d, %Y"),
            (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        ]

        for pattern, fmt in patterns:
            match = re.search(pattern, date_text)
            if match:
                try:
                    return datetime.strptime(match.group(1), fmt)
                except ValueError:
                    continue

        return None

    def _extract_summary_enhanced(self, elem: BeautifulSoup) -> str:
        """Extract article summary with enhanced search.

        Args:
            elem: The article element.

        Returns:
            Summary text, or empty string if not found.
        """
        # Get parent elements
        elements_to_search = [elem]
        parent = elem.parent
        for _ in range(3):
            if parent and parent.name not in ["body", "html", "[document]"]:
                elements_to_search.append(parent)
                parent = parent.parent
            else:
                break

        for container in elements_to_search:
            # Summary selectors
            summary_selectors = [
                '[class*="summary"]',
                '[class*="excerpt"]',
                '[class*="description"]',
                '[class*="preview"]',
                '[class*="snippet"]',
                '[data-testid*="summary"]',
                '[data-testid*="excerpt"]',
            ]

            for selector in summary_selectors:
                try:
                    summary_elem = container.select_one(selector)
                    if summary_elem:
                        text = summary_elem.get_text(strip=True)
                        if text and len(text) > 20:
                            return text
                except Exception:
                    continue

            # Try paragraph elements
            p_elem = container.select_one("p")
            if p_elem:
                text = p_elem.get_text(strip=True)
                if text and len(text) > 20:
                    return text

        return ""
