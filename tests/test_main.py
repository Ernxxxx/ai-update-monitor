"""Tests for app.main module -- process_articles smoke test."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.config import Config
from app.db import get_article, init_db
from app.main import fetch_all_articles, process_articles
from app.sources.base import Article


def _make_config(db_path: str) -> Config:
    """Create a minimal Config for testing."""
    return Config(
        discord_bot_token="test-token",
        discord_guild_id="123456",
        llm_base_url="https://api.example.com",
        llm_api_key=None,  # skip LLM
        llm_model="test",
        check_interval=600,
        db_path=db_path,
        xai_api_key=None,
        x_bearer_token=None,
    )


def _make_article(idx: int = 0, source: str = "openai") -> Article:
    return Article(
        url=f"https://example.com/article-{idx}",
        title=f"Test Article {idx}",
        content=f"Content for article {idx}",
        source=source,
        published_at=datetime.now(timezone.utc),
    )


class TestProcessArticles:
    @patch("app.main.DiscordBot")
    @patch("app.main.fetch_all_articles")
    def test_dry_run_does_not_save(self, mock_fetch, mock_bot_cls, db_path):
        """dry_run should log but NOT save to DB."""
        mock_fetch.return_value = [_make_article(0)]
        mock_bot = MagicMock()
        mock_bot.send_embed.return_value = True
        mock_bot_cls.return_value = mock_bot

        config = _make_config(db_path)
        processed = process_articles(config, dry_run=True, fallback=True)

        assert processed == 1
        # Should NOT call ensure_channels in dry_run
        mock_bot.ensure_channels.assert_not_called()
        # DB should be empty
        assert get_article(db_path, "https://example.com/article-0") is None

    @patch("app.main.DiscordBot")
    @patch("app.main.fetch_all_articles")
    def test_no_articles_returns_zero(self, mock_fetch, mock_bot_cls, db_path):
        mock_fetch.return_value = []
        config = _make_config(db_path)
        processed = process_articles(config, dry_run=True)
        assert processed == 0

    @patch("app.main.DiscordBot")
    @patch("app.main.fetch_all_articles")
    def test_skips_already_notified(self, mock_fetch, mock_bot_cls, db_path):
        """Articles already in DB with notified_at should be skipped."""
        from app.db import save_article as db_save
        from app.utils import compute_hash

        article = _make_article(0)
        # Pre-populate DB with matching content_hash so it's not treated as "updated"
        db_save(db_path, {
            "url": "https://example.com/article-0",
            "source": "openai",
            "title": "Test Article 0",
            "notified_at": "2026-01-01T00:00:00+00:00",
            "content_hash": compute_hash(article.content),
        })

        mock_fetch.return_value = [_make_article(0)]
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot

        config = _make_config(db_path)
        processed = process_articles(config, dry_run=True, fallback=True)
        assert processed == 0

    @patch("app.main.DiscordBot")
    @patch("app.main.fetch_all_articles")
    def test_without_fallback_skips_no_summary(self, mock_fetch, mock_bot_cls, db_path):
        """Without --fallback, articles with no LLM summary should be skipped."""
        mock_fetch.return_value = [_make_article(0)]
        mock_bot = MagicMock()
        mock_bot_cls.return_value = mock_bot

        config = _make_config(db_path)
        # llm_api_key is None so no summary will be produced, and fallback=False
        processed = process_articles(config, dry_run=True, fallback=False)
        assert processed == 0


class TestFetchAllArticles:
    @patch("app.main.get_all_sources")
    def test_parallel_fetch(self, mock_get_sources):
        """Should fetch from all sources and combine results."""
        source1 = MagicMock()
        source1.name = "openai"
        source1.fetch_articles.return_value = [_make_article(0, "openai")]

        source2 = MagicMock()
        source2.name = "anthropic"
        source2.fetch_articles.return_value = [_make_article(1, "anthropic")]

        mock_get_sources.return_value = [source1, source2]

        articles = fetch_all_articles()
        assert len(articles) == 2
        sources = {a.source for a in articles}
        assert sources == {"openai", "anthropic"}

    @patch("app.main.get_all_sources")
    def test_handles_source_failure(self, mock_get_sources):
        """Should return results from working sources even if one fails."""
        good_source = MagicMock()
        good_source.name = "openai"
        good_source.fetch_articles.return_value = [_make_article(0)]

        bad_source = MagicMock()
        bad_source.name = "broken"
        bad_source.fetch_articles.side_effect = RuntimeError("network error")

        mock_get_sources.return_value = [good_source, bad_source]

        articles = fetch_all_articles()
        assert len(articles) == 1
