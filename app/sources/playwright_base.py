"""Playwright-based source for sites with bot protection."""

import logging
from typing import Optional, Literal
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, Browser, Page, Playwright

logger = logging.getLogger(__name__)

# Type for wait_until parameter
WaitUntilType = Literal["commit", "domcontentloaded", "load", "networkidle"]


class PlaywrightMixin:
    """Mixin class providing Playwright browser functionality."""

    _playwright: Optional[Playwright] = None
    _browser: Optional[Browser] = None

    @classmethod
    def get_browser(cls) -> Browser:
        """Get or create a shared browser instance."""
        if cls._browser is None or not cls._browser.is_connected():
            if cls._playwright is None:
                cls._playwright = sync_playwright().start()
            cls._browser = cls._playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-gpu',
                    '--disable-extensions',
                ]
            )
        return cls._browser

    @classmethod
    def close_browser(cls) -> None:
        """Close the shared browser instance."""
        if cls._browser:
            cls._browser.close()
            cls._browser = None
        if cls._playwright:
            cls._playwright.stop()
            cls._playwright = None

    @contextmanager
    def get_page(
        self,
        url: str,
        wait_selector: str | None = None,
        timeout: int = 60000,
        wait_until: WaitUntilType = "domcontentloaded",
        extra_wait: int = 3000,
    ):
        """Context manager for getting a page with content loaded.

        Args:
            url: URL to navigate to
            wait_selector: CSS selector to wait for (optional)
            timeout: Timeout in milliseconds (default: 60s)
            wait_until: When to consider navigation done:
                - "commit": when response is received
                - "domcontentloaded": when DOM is ready (fast, recommended)
                - "load": when load event fires
                - "networkidle": when no network activity (slow, may timeout)
            extra_wait: Additional wait time in ms after page load (default: 3s)

        Yields:
            Page object with content loaded
        """
        browser = self.get_browser()
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            java_script_enabled=True,
        )
        page = context.new_page()

        try:
            # Block unnecessary resources for speed
            page.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,mp4,webm}", lambda route: route.abort())

            logger.info(f"Navigating to {url} (wait_until={wait_until}, timeout={timeout}ms)")
            page.goto(url, wait_until=wait_until, timeout=timeout)

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=min(timeout, 10000))
                except Exception:
                    logger.debug(f"Selector {wait_selector} not found, continuing anyway")

            # Extra wait to ensure JS execution and dynamic content loads
            if extra_wait > 0:
                page.wait_for_timeout(extra_wait)

            yield page
        finally:
            context.close()


def fetch_with_playwright(
    url: str,
    wait_selector: str | None = None,
    timeout: int = 60000,
    wait_until: WaitUntilType = "domcontentloaded",
    extra_wait: int = 3000,
) -> str:
    """Fetch page content using Playwright.

    Args:
        url: URL to fetch
        wait_selector: CSS selector to wait for
        timeout: Timeout in milliseconds (default: 60s)
        wait_until: When to consider navigation done (default: domcontentloaded)
        extra_wait: Additional wait time in ms after page load (default: 3s)

    Returns:
        Page HTML content
    """
    mixin = PlaywrightMixin()
    try:
        with mixin.get_page(url, wait_selector, timeout, wait_until, extra_wait) as page:
            return page.content()
    except Exception as e:
        logger.error(f"Playwright fetch failed for {url}: {e}")
        raise
