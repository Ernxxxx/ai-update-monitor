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

    discord_webhook_url: str
    llm_base_url: str
    llm_api_key: Optional[str]  # Optional: if not set, LLM summarization is skipped
    llm_model: str
    check_interval: int
    db_path: str

    @classmethod
    def from_env(cls) -> "Config":
        """Create Config instance from environment variables.

        Returns:
            Config: Configuration instance with values from environment.

        Raises:
            ValueError: If required environment variables are missing.
        """
        load_dotenv()

        discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not discord_webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is required")

        llm_api_key = os.getenv("LLM_API_KEY")
        # LLM_API_KEY is optional - if not set, summarization will be skipped

        return cls(
            discord_webhook_url=discord_webhook_url,
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_api_key=llm_api_key,
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            check_interval=int(os.getenv("CHECK_INTERVAL", "600")),
            db_path=os.getenv("DB_PATH", "state.db"),
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
