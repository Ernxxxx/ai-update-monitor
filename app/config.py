"""Configuration module for ai-update-monitor.

Loads environment variables from .env file using python-dotenv.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    discord_bot_token: str
    discord_guild_id: str
    llm_base_url: str
    llm_api_key: Optional[str]  # Optional: if not set, LLM summarization is skipped
    llm_model: str
    check_interval: int
    db_path: str
    xai_api_key: Optional[str]  # Optional: xAI API key for Grok (future use)
    x_bearer_token: Optional[str]  # Optional: X API Bearer Token for Twitter news

    @classmethod
    def from_env(cls) -> "Config":
        """Create Config instance from environment variables.

        Returns:
            Config: Configuration instance with values from environment.

        Raises:
            ValueError: If required environment variables are missing.
        """
        load_dotenv()

        discord_bot_token = os.getenv("DISCORD_BOT_TOKEN")
        discord_guild_id = os.getenv("DISCORD_GUILD_ID")

        if not discord_bot_token:
            raise ValueError("DISCORD_BOT_TOKEN is required")
        if not discord_guild_id:
            raise ValueError("DISCORD_GUILD_ID is required")

        llm_api_key = os.getenv("LLM_API_KEY")
        # LLM_API_KEY is optional - if not set, summarization will be skipped

        return cls(
            discord_bot_token=discord_bot_token,
            discord_guild_id=discord_guild_id,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=llm_api_key,
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            check_interval=int(os.getenv("CHECK_INTERVAL", "600")),
            db_path=os.getenv("DB_PATH", "state.db"),
            xai_api_key=os.getenv("XAI_API_KEY"),
            x_bearer_token=os.getenv("X_BEARER_TOKEN"),
        )


_config: Optional[Config] = None


def get_config() -> Config:
    """Get the singleton Config instance.

    Returns:
        Config: The application configuration.
    """
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def reset_config() -> None:
    """Reset the singleton Config instance (useful for testing)."""
    global _config
    _config = None
