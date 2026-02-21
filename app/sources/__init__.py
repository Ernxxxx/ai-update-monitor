"""News sources for AI update monitoring.

This module provides parsers for various AI company news sources.
"""

from .anthropic_source import AnthropicSource
from .base import Article, BaseSource
from .gemini_source import GeminiSource
from .openai_source import OpenAISource
from .playwright_base import PlaywrightMixin, fetch_with_playwright
from .status_source import StatusSource
from .x_source import XNewsSource, XTipsSource, XProductSource

__all__ = [
    "Article",
    "BaseSource",
    "OpenAISource",
    "AnthropicSource",
    "GeminiSource",
    "XNewsSource",
    "XTipsSource",
    "XProductSource",
    "StatusSource",
    "PlaywrightMixin",
    "fetch_with_playwright",
    "get_all_sources",
]


def get_all_sources() -> list[BaseSource]:
    """Get instances of all available news sources.

    Returns:
        List of BaseSource instances for all supported AI news sources.
        X sources are included only if X_BEARER_TOKEN is configured.
    """
    sources: list[BaseSource] = [
        OpenAISource(),
        AnthropicSource(),
        GeminiSource(),
        StatusSource(),
    ]

    x_news = XNewsSource()
    if x_news.bearer_token:
        sources.append(x_news)
        sources.append(XTipsSource())
        sources.append(XProductSource())

    return sources
