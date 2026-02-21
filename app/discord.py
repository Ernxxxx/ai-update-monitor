"""Discord Bot API notification module.

Uses Discord REST API (no gateway/WebSocket needed).
Automatically creates channels and sends rich embeds per source.
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]

# Source -> channel name mapping
SOURCE_CHANNELS: dict[str, str] = {
    "openai": "openai-updates",
    "anthropic": "anthropic-updates",
    "gemini": "gemini-updates",
    "ai_news": "ai-news",
    "ai_tips": "ai-tips",
    "daily_digest": "daily-digest",
    "weekly_digest": "weekly-digest",
    "status": "status-alerts",
}

# Source display config for embeds
SOURCE_CONFIG: dict[str, dict] = {
    "openai": {"name": "OpenAI", "color": 0x10A37F, "footer": "公式発表"},
    "anthropic": {"name": "Anthropic", "color": 0xD4A574, "footer": "公式発表"},
    "gemini": {"name": "Gemini", "color": 0x4285F4, "footer": "公式発表"},
    "ai_news": {"name": "AI News", "color": 0xFF6B35, "footer": "AI News"},
    "ai_tips": {"name": "AI Tips", "color": 0x9B59B6, "footer": "X Tips"},
    "daily_digest": {"name": "Daily Digest", "color": 0x3498DB, "footer": "日次まとめ"},
    "weekly_digest": {"name": "Weekly Digest", "color": 0x2ECC71, "footer": "週次まとめ"},
    "status": {"name": "Status", "color": 0xE74C3C, "footer": "障害情報"},
}

CATEGORY_NAME = "AI Updates"


class DiscordBot:
    """Discord Bot client using REST API only (no gateway)."""

    def __init__(self, token: str, guild_id: str):
        self.token = token
        self.guild_id = guild_id
        self.headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }
        self._channel_cache: dict[str, str] = {}  # source -> channel_id

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[dict]:
        """Make a Discord API request with retry and rate limit handling."""
        url = f"{DISCORD_API_BASE}{endpoint}"
        for attempt in range(MAX_RETRIES):
            try:
                resp = requests.request(
                    method, url, headers=self.headers, timeout=15, **kwargs
                )

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = resp.json().get("retry_after", 2)
                    logger.warning(f"Rate limited, waiting {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else None

            except requests.RequestException as e:
                logger.warning(f"API request attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAYS[attempt])
                else:
                    raise

        return None

    def ensure_channels(self) -> None:
        """Create the category and per-source channels if they don't exist."""
        channels = self._request("GET", f"/guilds/{self.guild_id}/channels")
        if not channels:
            logger.error("Failed to fetch guild channels")
            return

        # Index existing channels by name
        existing_text: dict[str, str] = {}   # name -> id
        existing_cats: dict[str, str] = {}   # name -> id
        for ch in channels:
            if ch["type"] == 0:  # GUILD_TEXT
                existing_text[ch["name"]] = ch["id"]
            elif ch["type"] == 4:  # GUILD_CATEGORY
                existing_cats[ch["name"].lower()] = ch["id"]

        # Find or create category
        category_id = existing_cats.get(CATEGORY_NAME.lower())
        if category_id is None:
            logger.info(f"Creating category: {CATEGORY_NAME}")
            cat = self._request(
                "POST",
                f"/guilds/{self.guild_id}/channels",
                json={"name": CATEGORY_NAME, "type": 4},
            )
            if cat:
                category_id = cat["id"]
            else:
                logger.error("Failed to create category")
                return

        # Create missing channels under the category
        for source, channel_name in SOURCE_CHANNELS.items():
            if channel_name in existing_text:
                self._channel_cache[source] = existing_text[channel_name]
                logger.info(f"Channel exists: #{channel_name} -> {source}")
            else:
                logger.info(f"Creating channel: #{channel_name}")
                ch = self._request(
                    "POST",
                    f"/guilds/{self.guild_id}/channels",
                    json={
                        "name": channel_name,
                        "type": 0,
                        "parent_id": category_id,
                    },
                )
                if ch:
                    self._channel_cache[source] = ch["id"]
                    logger.info(f"Created channel: #{channel_name} -> {source}")
                else:
                    logger.error(f"Failed to create channel: #{channel_name}")

    def get_channel_id(self, source: str) -> Optional[str]:
        """Get channel ID for a source, initializing channels if needed."""
        if not self._channel_cache:
            self.ensure_channels()
        return self._channel_cache.get(source)

    def send_embed(
        self,
        source: str,
        title: str,
        summary: Optional[str],
        url: str,
        dry_run: bool = False,
    ) -> bool:
        """Send a rich embed notification to the source-specific channel.

        Args:
            source: Article source name (e.g. "openai").
            title: Article title.
            summary: LLM-generated summary text.
            url: Article URL.
            dry_run: If True, log instead of sending.

        Returns:
            True if successful, False otherwise.
        """
        channel_name = SOURCE_CHANNELS.get(source, source)
        channel_id = self.get_channel_id(source)

        if not channel_id:
            logger.error(f"No channel for source: {source}")
            return False

        config = SOURCE_CONFIG.get(source, {"name": source.upper(), "color": 0x808080})

        # Build embed
        embed = {
            "title": title[:256],  # Discord title limit
            "color": config["color"],
            "footer": {"text": f"{config['name']} | {config.get('footer', config['name'])}"},
        }
        if url:
            embed["url"] = url

        # Add description only if summary has content
        if summary:
            description = summary
            if len(description) > 4000:
                description = description[:3997] + "..."
            embed["description"] = description

        if dry_run:
            logger.info(f"[DRY-RUN] #{channel_name}: {title}")
            return True

        try:
            self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                json={"embeds": [embed]},
            )
            logger.info(f"Sent to #{channel_name}: {title}")
            return True
        except Exception as e:
            logger.error(f"Failed to send to #{channel_name}: {e}")
            return False

    def send_url(
        self,
        source: str,
        url: str,
        dry_run: bool = False,
    ) -> bool:
        """Send a plain URL message to the source-specific channel.

        Discord auto-generates a preview card from the URL.

        Args:
            source: Article source name.
            url: URL to send.
            dry_run: If True, log instead of sending.

        Returns:
            True if successful, False otherwise.
        """
        channel_name = SOURCE_CHANNELS.get(source, source)
        channel_id = self.get_channel_id(source)

        if not channel_id:
            logger.error(f"No channel for source: {source}")
            return False

        if dry_run:
            logger.info(f"[DRY-RUN] #{channel_name}: {url}")
            return True

        try:
            self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                json={"content": url},
            )
            logger.info(f"Sent to #{channel_name}: {url}")
            return True
        except Exception as e:
            logger.error(f"Failed to send to #{channel_name}: {e}")
            return False
