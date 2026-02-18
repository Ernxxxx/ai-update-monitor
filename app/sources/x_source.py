"""X (Twitter) sources using X API v2 Recent Search.

Provides two sources:
- XNewsSource: Official AI company announcements -> #ai-news
- XTipsSource: AI tips, tutorials, prompt engineering -> #ai-tips
"""

import logging
import os
from datetime import datetime

import requests

from .base import Article, BaseSource

logger = logging.getLogger(__name__)

TIMEOUT = 30

# --- Account lists ---

# Official AI company accounts (news/announcements)
# NOTE: OpenAI, AnthropicAI, GoogleDeepMind, GoogleAI are excluded here
# because they already have dedicated channels (#openai-updates, etc.).
AI_NEWS_ACCOUNTS = [
    "xai",
    "MistralAI",
    "MetaAI",
    "nvidia",
    "huggingface",
    "MSFTResearch",
    "IBMResearch",
    "StabilityAI",
    "CohereAI",
    "Aboratory",
]

# Accounts that share AI tips, tutorials, developer content
# NOTE: ChatGPTapp, ClaudeAI removed (official product accounts, not tips).
# llaboratory, kaborooo, skiaborooo removed (noisy / may not exist).
AI_TIPS_ACCOUNTS = [
    "OpenAIDevs",
    "LangChainAI",
    "LlamaIndex",
    "weights_biases",
    "AndrewYNg",
    "GoogleColab",
    "svpino",
    "hwchase17",
    "jerryjliu0",
    "emaboratory",
]


class _XBaseSource(BaseSource):
    """Base class for X API v2 sources. Not used directly."""

    API_URL = "https://api.x.com/2/tweets/search/recent"

    def __init__(self):
        self.bearer_token = os.getenv("X_BEARER_TOKEN", "")

    def _build_query(self) -> str:
        raise NotImplementedError

    def fetch_articles(self, limit: int = 10) -> list[Article]:
        if not self.bearer_token:
            logger.info(f"X_BEARER_TOKEN not set, skipping {self.name}")
            return []
        try:
            return self._search_tweets(limit)
        except Exception as e:
            logger.error(f"Failed to fetch from X API ({self.name}): {e}")
            return []

    def _search_tweets(self, limit: int) -> list[Article]:
        query = self._build_query()
        params = {
            "query": query,
            "max_results": max(min(limit, 100), 10),  # X API requires 10-100
            "tweet.fields": "created_at,author_id,text,entities",
            "expansions": "author_id",
            "user.fields": "username,name",
        }
        headers = {"Authorization": f"Bearer {self.bearer_token}"}

        resp = requests.get(
            self.API_URL, headers=headers, params=params, timeout=TIMEOUT
        )
        resp.raise_for_status()

        data = resp.json()
        return self._parse_response(data, limit)

    def _parse_response(self, data: dict, limit: int) -> list[Article]:
        tweets = data.get("data", [])
        if not tweets:
            logger.info(f"No tweets found for {self.name}")
            return []

        # Build user lookup
        users: dict[str, dict] = {}
        for user in data.get("includes", {}).get("users", []):
            users[user["id"]] = {
                "username": user.get("username", ""),
                "name": user.get("name", ""),
            }

        articles: list[Article] = []
        seen_urls: set[str] = set()

        for tweet in tweets[:limit]:
            tweet_id = tweet.get("id", "")
            text = tweet.get("text", "")
            author_id = tweet.get("author_id", "")
            created_at_str = tweet.get("created_at", "")

            if not tweet_id or not text:
                continue

            user_info = users.get(author_id, {})
            username = user_info.get("username", "unknown")
            display_name = user_info.get("name", username)

            url = f"https://x.com/{username}/status/{tweet_id}"
            if url in seen_urls:
                continue
            seen_urls.add(url)

            published_at = None
            if created_at_str:
                try:
                    published_at = datetime.fromisoformat(
                        created_at_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            title = self._build_title(display_name, text)
            content = f"@{username}: {text}"

            articles.append(
                Article(
                    url=url,
                    title=title,
                    content=content,
                    source=self.name,
                    published_at=published_at,
                )
            )

        logger.info(f"Found {len(articles)} tweets for {self.name}")
        return articles

    @staticmethod
    def _build_title(display_name: str, text: str) -> str:
        first_line = text.split("\n")[0].strip()
        words = [w for w in first_line.split() if not w.startswith("http")]
        clean_text = " ".join(words).strip()
        if not clean_text:
            clean_text = text[:80]
        if len(clean_text) > 80:
            clean_text = clean_text[:77] + "..."
        return f"{display_name}: {clean_text}"


class XNewsSource(_XBaseSource):
    """AI news from official company accounts -> #ai-news."""

    name = "ai_news"

    def _build_query(self) -> str:
        from_clauses = " OR ".join(f"from:{a}" for a in AI_NEWS_ACCOUNTS)
        return f"({from_clauses}) -is:retweet -is:reply"


class XTipsSource(_XBaseSource):
    """AI tips and tutorials from developer/educator accounts -> #ai-tips."""

    name = "ai_tips"

    # Keyword filter to keep only educational / useful content.
    _KEYWORD_FILTER = (
        "(tip OR tutorial OR \"how to\" OR prompt OR workflow"
        " OR guide OR thread OR learn)"
    )

    def _build_query(self) -> str:
        from_clauses = " OR ".join(f"from:{a}" for a in AI_TIPS_ACCOUNTS)
        return f"({from_clauses}) {self._KEYWORD_FILTER} -is:retweet -is:reply"
