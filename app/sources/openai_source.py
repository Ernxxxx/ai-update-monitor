"""OpenAI news source parser."""

import logging
import time
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

from .base import Article, BaseSource
from .playwright_base import PlaywrightMixin, fetch_with_playwright

logger = logging.getLogger(__name__)

# More realistic browser headers to avoid bot detection
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

TIMEOUT = 15  # seconds
REQUEST_DELAY = 2  # seconds between requests
CONTENT_MAX_LENGTH = 3000  # Maximum characters for article content


class OpenAISource(BaseSource, PlaywrightMixin):
    """Parser for OpenAI official news sources."""

    name = "openai"

    # RSS feeds (preferred - less likely to be blocked)
    RSS_FEEDS = [
        "https://openai.com/blog/rss.xml",
        "https://openai.com/blog/rss",
        "https://openai.com/rss.xml",
        "https://openai.com/feed",
    ]

    # Web pages to scrape (fallback)
    NEWS_URLS = [
        "https://openai.com/news/",
        "https://openai.com/blog/",
        "https://openai.com/research/",
        "https://openai.com/index/",
    ]

    def __init__(self):
        """Initialize the OpenAI source with a session."""
        self._session = None

    def _get_session(self) -> requests.Session:
        """Get or create a requests session with proper headers.

        Returns:
            Configured requests Session object.
        """
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update(HEADERS)
        return self._session

    def fetch_articles(self, limit: int = 10) -> list[Article]:
        """Fetch the latest articles from OpenAI news.

        Tries RSS feeds first (preferred), then falls back to web scraping.

        Args:
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects. Returns empty list on failure.
        """
        articles: list[Article] = []

        # Strategy 1: Try RSS feeds first (less likely to be blocked)
        for rss_url in self.RSS_FEEDS:
            if len(articles) >= limit:
                break
            try:
                logger.info(f"Trying RSS feed: {rss_url}")
                new_articles = self._fetch_from_rss(rss_url, limit - len(articles))
                if new_articles:
                    articles.extend(new_articles)
                    logger.info(f"Found {len(new_articles)} articles from RSS: {rss_url}")
                    break  # Success, no need to try other RSS feeds
            except Exception as e:
                logger.debug(f"RSS feed {rss_url} failed: {e}")
            time.sleep(REQUEST_DELAY)

        # Strategy 2: Try web scraping if RSS didn't work
        if len(articles) < limit:
            for page_url in self.NEWS_URLS:
                if len(articles) >= limit:
                    break
                try:
                    logger.info(f"Trying web page: {page_url}")
                    remaining = limit - len(articles)
                    new_articles = self._fetch_from_web_page(page_url, remaining)
                    if new_articles:
                        # Deduplicate by URL
                        existing_urls = {a.url for a in articles}
                        for article in new_articles:
                            if article.url not in existing_urls and len(articles) < limit:
                                articles.append(article)
                                existing_urls.add(article.url)
                        logger.info(f"Found articles from web page: {page_url}")
                except requests.exceptions.HTTPError as e:
                    if e.response is not None and e.response.status_code == 403:
                        logger.info(f"Got 403 from {page_url}, falling back to Playwright")
                        try:
                            remaining = limit - len(articles)
                            new_articles = self._fetch_with_playwright(page_url, remaining)
                            if new_articles:
                                existing_urls = {a.url for a in articles}
                                for article in new_articles:
                                    if article.url not in existing_urls and len(articles) < limit:
                                        articles.append(article)
                                        existing_urls.add(article.url)
                                logger.info(f"Found articles via Playwright from: {page_url}")
                        except Exception as pw_error:
                            logger.warning(f"Playwright fallback failed for {page_url}: {pw_error}")
                    else:
                        logger.warning(f"Failed to fetch from {page_url}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to fetch from {page_url}: {e}")
                time.sleep(REQUEST_DELAY)

        return articles[:limit]

    def _fetch_from_rss(self, rss_url: str, limit: int) -> list[Article]:
        """Fetch articles from an RSS feed.

        Args:
            rss_url: URL of the RSS feed.
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        # feedparser handles its own requests, but we can pass headers
        feed = feedparser.parse(rss_url, request_headers=HEADERS)

        if feed.bozo and not feed.entries:
            # Feed parsing failed completely
            raise ValueError(f"Failed to parse RSS feed: {feed.bozo_exception}")

        articles: list[Article] = []
        for entry in feed.entries[:limit]:
            try:
                # Extract URL
                url = entry.get("link", "")
                if not url:
                    continue

                # Extract title
                title = entry.get("title", "").strip()
                if not title:
                    continue

                # Extract content/summary
                content = ""
                if "content" in entry and entry.content:
                    content = entry.content[0].get("value", "")
                elif "summary" in entry:
                    content = entry.get("summary", "")

                # Extract publication date
                published_at = None
                if "published_parsed" in entry and entry.published_parsed:
                    try:
                        published_at = datetime(*entry.published_parsed[:6])
                    except (TypeError, ValueError):
                        pass
                elif "updated_parsed" in entry and entry.updated_parsed:
                    try:
                        published_at = datetime(*entry.updated_parsed[:6])
                    except (TypeError, ValueError):
                        pass

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

        return articles

    def _fetch_from_web_page(self, page_url: str, limit: int) -> list[Article]:
        """Fetch articles by scraping a web page.

        Args:
            page_url: URL of the page to scrape.
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        session = self._get_session()

        # First, make a request to the main page to get cookies
        try:
            main_response = session.get(
                "https://openai.com/",
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            main_response.raise_for_status()
            time.sleep(1)  # Small delay after initial request
        except Exception as e:
            logger.debug(f"Initial request to openai.com failed: {e}")

        # Now fetch the actual page
        response = session.get(
            page_url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        articles: list[Article] = []

        # Try multiple selector strategies
        article_links = self._find_article_links(soup)

        seen_urls: set[str] = set()
        for link in article_links:
            if len(articles) >= limit:
                break

            href = link.get("href", "")
            if not href or href in seen_urls:
                continue

            # Skip non-article links
            if self._is_skip_url(href):
                continue

            # Build full URL if relative
            if href.startswith("/"):
                url = f"https://openai.com{href}"
            elif href.startswith("http"):
                url = href
            else:
                continue

            seen_urls.add(href)

            # Extract title from link text or nested elements
            title = self._extract_title(link)
            if not title:
                continue

            # Extract published date if available
            published_at = self._extract_date(link)

            # Fetch article content from individual page
            content = self._fetch_article_content(url)
            time.sleep(REQUEST_DELAY)  # Be polite between requests

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

    def _fetch_with_playwright(self, url: str, limit: int) -> list[Article]:
        """Fetch articles using Playwright for bot-protected pages.

        Args:
            url: URL of the page to scrape.
            limit: Maximum number of articles to fetch.

        Returns:
            List of Article objects.
        """
        # Use domcontentloaded (faster) with longer timeout for heavy JS sites
        html = fetch_with_playwright(
            url,
            wait_selector="a",
            timeout=60000,  # 60 seconds
            wait_until="domcontentloaded",
            extra_wait=5000,  # 5 seconds for JS to render
        )
        soup = BeautifulSoup(html, "html.parser")
        articles: list[Article] = []

        # Use the same article finding logic as _fetch_from_web_page
        article_links = self._find_article_links(soup)

        seen_urls: set[str] = set()
        for link in article_links:
            if len(articles) >= limit:
                break

            href = link.get("href", "")
            if not href or href in seen_urls:
                continue

            # Skip non-article links
            if self._is_skip_url(href):
                continue

            # Build full URL if relative
            if href.startswith("/"):
                full_url = f"https://openai.com{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                continue

            seen_urls.add(href)

            # Extract title from link text or nested elements
            title = self._extract_title(link)
            if not title:
                continue

            # Extract published date if available
            published_at = self._extract_date(link)

            # Fetch article content from individual page
            content = self._fetch_article_content(full_url)
            time.sleep(REQUEST_DELAY)  # Be polite between requests

            articles.append(
                Article(
                    url=full_url,
                    title=title,
                    content=content,
                    source=self.name,
                    published_at=published_at,
                )
            )

        return articles

    def _find_article_links(self, soup: BeautifulSoup) -> list:
        """Find article links using multiple selector strategies.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            List of link elements.
        """
        # Strategy 1: Links to index pages (common OpenAI pattern)
        links = soup.select("a[href*='/index/']")
        if links:
            return links

        # Strategy 2: Links to blog posts
        links = soup.select("a[href*='/blog/']")
        if links:
            return links

        # Strategy 3: Links to research pages
        links = soup.select("a[href*='/research/']")
        if links:
            return links

        # Strategy 4: Article elements
        links = soup.select("article a")
        if links:
            return links

        # Strategy 5: Common card patterns
        links = soup.select(
            ".news-item a, .post-card a, [data-testid='news-card'] a, "
            "[data-testid='post-card'] a, .card a"
        )
        if links:
            return links

        # Strategy 6: Any links that look like articles
        all_links = soup.select("a[href]")
        article_links = []
        for link in all_links:
            href = link.get("href", "")
            if any(pattern in href for pattern in ["/index/", "/blog/", "/research/", "/news/"]):
                article_links.append(link)
        return article_links

    def _is_skip_url(self, href: str) -> bool:
        """Check if a URL should be skipped.

        Args:
            href: URL or path to check.

        Returns:
            True if the URL should be skipped.
        """
        skip_patterns = [
            "/careers",
            "/about",
            "/api",
            "/pricing",
            "/enterprise",
            "/safety",
            "/charter",
            "#",
            "javascript:",
            "/login",
            "/signup",
        ]
        return any(pattern in href.lower() for pattern in skip_patterns)

    def _extract_title(self, element) -> str:
        """Extract title from a link element.

        Args:
            element: BeautifulSoup element.

        Returns:
            Title string or empty string if not found.
        """
        # Try direct text
        title = element.get_text(strip=True)
        if title and len(title) > 5:  # Avoid very short titles like "Read"
            return title

        # Try nested heading elements
        for tag in ["h1", "h2", "h3", "h4", ".title", ".heading"]:
            title_elem = element.select_one(tag)
            if title_elem:
                title = title_elem.get_text(strip=True)
                if title:
                    return title

        # Try parent element
        parent = element.parent
        if parent:
            for tag in ["h1", "h2", "h3", "h4", ".title", ".heading"]:
                title_elem = parent.select_one(tag)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    if title:
                        return title

        return ""

    def _extract_date(self, element) -> datetime | None:
        """Try to extract publication date from an element.

        Args:
            element: BeautifulSoup element to search for date.

        Returns:
            datetime object if found, None otherwise.
        """
        # Check the element and its ancestors for date information
        elements_to_check = [element]
        if element.parent:
            elements_to_check.append(element.parent)
        if element.parent and element.parent.parent:
            elements_to_check.append(element.parent.parent)

        for elem in elements_to_check:
            # Try time element with datetime attribute
            time_elem = elem.select_one("time[datetime]")
            if time_elem:
                try:
                    date_str = time_elem.get("datetime", "")
                    # ISO format: 2024-01-15T00:00:00Z
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Try data attribute
            date_attr = elem.get("data-date") or elem.get("data-published")
            if date_attr:
                try:
                    return datetime.fromisoformat(date_attr.replace("Z", "+00:00"))
                except ValueError:
                    pass

            # Try to find date text
            date_elem = elem.select_one(".date, .published, [data-testid='date'], .meta-date")
            if date_elem:
                date_text = date_elem.get_text(strip=True)
                parsed = self._parse_date_text(date_text)
                if parsed:
                    return parsed

        return None

    def _parse_date_text(self, text: str) -> datetime | None:
        """Parse various date text formats.

        Args:
            text: Date string to parse.

        Returns:
            datetime object if parsed successfully, None otherwise.
        """
        formats = [
            "%B %d, %Y",      # January 15, 2024
            "%b %d, %Y",      # Jan 15, 2024
            "%Y-%m-%d",       # 2024-01-15
            "%d %B %Y",       # 15 January 2024
            "%d %b %Y",       # 15 Jan 2024
            "%m/%d/%Y",       # 01/15/2024
        ]

        for fmt in formats:
            try:
                return datetime.strptime(text.strip(), fmt)
            except ValueError:
                continue

        return None

    def _fetch_article_content(self, url: str) -> str:
        """Fetch article content from an individual article page.

        Args:
            url: URL of the article page.

        Returns:
            Article content text, limited to CONTENT_MAX_LENGTH characters.
            Returns empty string on failure.
        """
        try:
            logger.debug(f"Fetching article content from: {url}")

            # Use Playwright to fetch the article page (handles JS-rendered content)
            # Use domcontentloaded with longer extra_wait (networkidle often times out)
            html = fetch_with_playwright(
                url,
                wait_selector="article, main, .post-content, .content",
                timeout=30000,  # 30 seconds
                wait_until="domcontentloaded",
                extra_wait=5000,  # 5 seconds for JS to render content
            )

            soup = BeautifulSoup(html, "html.parser")

            # Remove unwanted elements
            for unwanted in soup.select(
                "script, style, nav, header, footer, aside, "
                ".nav, .header, .footer, .sidebar, .menu, .navigation, "
                ".social-share, .related-posts, .comments, .advertisement"
            ):
                unwanted.decompose()

            # Try multiple selectors for article content
            content_selectors = [
                "article",
                ".post-content",
                ".article-content",
                ".entry-content",
                "main .content",
                "main",
                ".content",
                "[data-testid='post-content']",
                ".prose",
                ".body-content",
            ]

            content = ""
            for selector in content_selectors:
                content_elem = soup.select_one(selector)
                if content_elem:
                    # Extract text, preserving paragraph structure
                    paragraphs = content_elem.find_all(["p", "h1", "h2", "h3", "h4", "li"])
                    if paragraphs:
                        content = "\n\n".join(
                            p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)
                        )
                    else:
                        content = content_elem.get_text(separator="\n", strip=True)

                    if content and len(content) > 100:  # Require meaningful content
                        break

            # Limit content length
            if content and len(content) > CONTENT_MAX_LENGTH:
                content = content[:CONTENT_MAX_LENGTH] + "..."

            return content

        except Exception as e:
            logger.warning(f"Failed to fetch article content from {url}: {e}")
            return ""
