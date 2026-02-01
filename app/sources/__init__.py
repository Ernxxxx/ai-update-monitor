"""News sources for AI update monitoring.

This module provides parsers for various AI company news sources.
"""

from .anthropic_source import AnthropicSource
from .base import Article, BaseSource
from .gemini_source import GeminiSource
from .openai_source import OpenAISource
from .playwright_base import PlaywrightMixin, fetch_with_playwright

__all__ = [
    "Article",
    "BaseSource",
    "OpenAISource",
    "AnthropicSource",
    "GeminiSource",
    "PlaywrightMixin",
    "fetch_with_playwright",
    "get_all_sources",
]


def get_all_sources() -> list[BaseSource]:
    """Get instances of all available news sources.

    Returns:
        List of BaseSource instances for all supported AI news sources.
    """
    return [
        OpenAISource(),
        AnthropicSource(),
        GeminiSource(),
    ]
