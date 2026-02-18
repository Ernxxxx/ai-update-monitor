"""Shared HTTP client with retry logic and common headers."""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Shared browser-like headers. Intentionally excludes Brotli ('br') from
# Accept-Encoding because the 'brotli' Python package may not be installed,
# causing responses to arrive as undecoded binary.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}

RSS_HEADERS = {
    "User-Agent": DEFAULT_HEADERS["User-Agent"],
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT = 15  # seconds
MAX_RETRIES = 3
BACKOFF_BASE = 1.5  # seconds; delays: 1.5, 3.0, 6.0


def create_session(extra_headers: Optional[dict] = None) -> requests.Session:
    """Create a requests.Session with shared default headers.

    Args:
        extra_headers: Additional headers to merge on top of defaults.

    Returns:
        Configured requests.Session.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if extra_headers:
        session.headers.update(extra_headers)
    return session


def fetch_with_retry(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    headers: Optional[dict] = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_retries: int = MAX_RETRIES,
    allow_redirects: bool = True,
) -> requests.Response:
    """Fetch a URL with exponential backoff retry on transient errors.

    Retries on connection errors, timeouts, and 5xx server errors.
    Does NOT retry on 4xx client errors (except 429 rate-limit).

    Args:
        url: URL to fetch.
        session: Optional pre-configured session. Uses a temporary one if None.
        headers: Optional headers to use (overrides session headers for this request).
        timeout: Request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        allow_redirects: Whether to follow redirects.

    Returns:
        requests.Response object.

    Raises:
        requests.RequestException: If all retries are exhausted.
    """
    _session = session or requests.Session()
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            resp = _session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=allow_redirects,
            )

            # Retry on 429 (rate limit) and 5xx (server error)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", BACKOFF_BASE * (2 ** attempt)))
                logger.warning(f"Rate limited on {url}, waiting {retry_after:.1f}s")
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500:
                logger.warning(f"Server error {resp.status_code} on {url}, retrying...")
                time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue

            resp.raise_for_status()
            return resp

        except requests.ConnectionError as e:
            last_error = e
            logger.warning(f"Connection error on {url} (attempt {attempt + 1}/{max_retries}): {e}")
        except requests.Timeout as e:
            last_error = e
            logger.warning(f"Timeout on {url} (attempt {attempt + 1}/{max_retries})")
        except requests.HTTPError:
            # 4xx errors (except 429 handled above) are not retried
            raise

        if attempt < max_retries - 1:
            delay = BACKOFF_BASE * (2 ** attempt)
            logger.debug(f"Retrying {url} in {delay:.1f}s")
            time.sleep(delay)

    # All retries exhausted
    if last_error:
        raise last_error
    raise requests.ConnectionError(f"Failed to fetch {url} after {max_retries} attempts")
