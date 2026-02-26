"""Utility functions for the AI update monitor."""

import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.

    Strips trailing slashes, removes tracking parameters (utm_*),
    lowercases the hostname, and forces HTTPS scheme.

    Args:
        url: Raw URL string.

    Returns:
        Normalized URL suitable for dedup comparison.
        Returns original string if parsing fails.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
    except Exception:
        return url

    # Force HTTPS
    scheme = "https"

    # Lowercase hostname, strip www.
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Remove trailing slash (but keep root "/")
    path = parsed.path.rstrip("/") or ""

    # Strip tracking query params
    _TRACKING_PARAMS = {
        "utm_source", "utm_medium", "utm_campaign",
        "utm_term", "utm_content", "ref", "source",
    }
    if parsed.query:
        qs = parse_qs(parsed.query, keep_blank_values=True)
        filtered = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        query = urlencode(filtered, doseq=True) if filtered else ""
    else:
        query = ""

    return urlunparse((scheme, netloc, path, parsed.params, query, parsed.fragment))


def compute_hash(text: str) -> str:
    """Compute SHA256 hash of the given text.

    Args:
        text: Input text to hash.

    Returns:
        Hexadecimal string representation of the SHA256 hash.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def truncate_text(text: str, max_length: int) -> str:
    """Truncate text to specified length with ellipsis.

    Args:
        text: Input text to truncate.
        max_length: Maximum length of the output (including ellipsis).

    Returns:
        Truncated text with '...' appended if truncation occurred,
        original text otherwise.
    """
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return "..." if max_length >= 3 else text[:max_length]
    return text[: max_length - 3] + "..."


def sanitize_for_log(text: str) -> str:
    """Mask sensitive information like API keys for safe logging.

    Masks patterns that look like API keys, tokens, or secrets.

    Args:
        text: Input text that may contain sensitive data.

    Returns:
        Text with sensitive patterns masked.
    """
    patterns = [
        # OpenAI API keys (sk-...)
        (r"sk-[a-zA-Z0-9]{20,}", "sk-****"),
        # Anthropic API keys (sk-ant-...)
        (r"sk-ant-[a-zA-Z0-9\-]{20,}", "sk-ant-****"),
        # Generic API key patterns
        (r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[a-zA-Z0-9\-_]{20,}", r"\1****"),
        # Bearer tokens
        (r"(?i)(bearer\s+)[a-zA-Z0-9\-_.]{20,}", r"\1****"),
        # Generic secret/token patterns
        (r"(?i)(secret|token|password)[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9\-_]{8,}", r"\1=****"),
    ]

    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)

    return result


def format_datetime(dt: datetime | None) -> str:
    """Format a datetime object to ISO8601 string.

    Args:
        dt: Datetime object to format, or None.

    Returns:
        ISO8601 formatted string, or empty string if dt is None.
    """
    if dt is None:
        return ""
    return dt.isoformat()


def parse_datetime(s: str) -> Optional[datetime]:
    """Parse an ISO8601 datetime string.

    Args:
        s: ISO8601 formatted datetime string.

    Returns:
        Parsed datetime object, or None if parsing fails or input is empty.
    """
    if not s:
        return None
    try:
        # Handle both with and without timezone
        # Python 3.11+ supports datetime.fromisoformat with Z suffix
        # For compatibility, replace Z with +00:00
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except ValueError:
        return None
