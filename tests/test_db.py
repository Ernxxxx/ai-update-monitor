"""Tests for app.db module -- SQLite operations."""

from datetime import datetime, timedelta, timezone

from app.db import (
    batch_check_articles,
    get_article,
    get_article_by_title_date,
    is_notified,
    is_updated,
    purge_old_articles,
    save_article,
)
from app.utils import compute_hash


# -- save_article + get_article ------------------------------------------------

class TestSaveAndGet:
    def test_save_and_retrieve(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "title": "Hello",
            "published_at": "2026-01-01T00:00:00+00:00",
            "content_hash": "abc123",
            "notified_at": "2026-01-01T12:00:00+00:00",
        })
        row = get_article(db_path, "https://example.com/1")
        assert row is not None
        assert row["title"] == "Hello"
        assert row["source"] == "openai"

    def test_upsert_preserves_notified_at(self, db_path):
        """ON CONFLICT should keep existing notified_at when new value is NULL."""
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "title": "V1",
            "notified_at": "2026-01-01T00:00:00+00:00",
        })
        # Second save with notified_at=None should NOT overwrite
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "title": "V2",
            "notified_at": None,
        })
        row = get_article(db_path, "https://example.com/1")
        assert row["title"] == "V2"
        assert row["notified_at"] == "2026-01-01T00:00:00+00:00"

    def test_get_article_not_found(self, db_path):
        assert get_article(db_path, "https://nonexistent.com") is None


# -- is_notified ---------------------------------------------------------------

class TestIsNotified:
    def test_not_notified_when_empty(self, db_path):
        assert is_notified(db_path, "https://example.com/1") is False

    def test_notified_by_url(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "notified_at": "2026-01-01T00:00:00+00:00",
        })
        assert is_notified(db_path, "https://example.com/1") is True

    def test_saved_but_not_notified(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "notified_at": None,
        })
        assert is_notified(db_path, "https://example.com/1") is False

    def test_notified_by_title_date(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "title": "Breaking News",
            "published_at": "2026-02-01T00:00:00+00:00",
            "notified_at": "2026-02-01T12:00:00+00:00",
        })
        # Different URL but same title+date
        assert is_notified(
            db_path,
            "https://other.com/x",
            title="Breaking News",
            published_at="2026-02-01T00:00:00+00:00",
            check_title_date=True,
        ) is True


# -- is_updated ----------------------------------------------------------------

class TestIsUpdated:
    def test_not_found_returns_false(self, db_path):
        assert is_updated(db_path, "https://example.com/1", "hash1") is False

    def test_same_hash_returns_false(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "content_hash": "hash1",
        })
        assert is_updated(db_path, "https://example.com/1", "hash1") is False

    def test_different_hash_returns_true(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "openai",
            "content_hash": "hash1",
        })
        assert is_updated(db_path, "https://example.com/1", "hash2") is True


# -- batch_check_articles ------------------------------------------------------

class TestBatchCheck:
    def test_empty_input(self, db_path):
        assert batch_check_articles(db_path, []) == {}

    def test_batch_by_url(self, db_path):
        for i in range(3):
            save_article(db_path, {
                "url": f"https://example.com/{i}",
                "source": "openai",
                "title": f"Article {i}",
                "notified_at": "2026-01-01T00:00:00+00:00",
            })
        result = batch_check_articles(
            db_path,
            ["https://example.com/0", "https://example.com/2", "https://missing.com"],
        )
        assert "https://example.com/0" in result
        assert "https://example.com/2" in result
        assert "https://missing.com" not in result

    def test_batch_by_title_date(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "anthropic",
            "title": "Release Notes",
            "published_at": "2026-02-10T00:00:00+00:00",
            "notified_at": "2026-02-10T12:00:00+00:00",
        })
        result = batch_check_articles(
            db_path,
            ["https://other.com/x"],
            titles_dates=[("Release Notes", "2026-02-10T00:00:00+00:00")],
        )
        assert "Release Notes::2026-02-10T00:00:00+00:00" in result


# -- purge_old_articles --------------------------------------------------------

class TestPurge:
    def test_purge_deletes_old(self, db_path):
        from app.db import get_connection

        # Insert an article with an old created_at
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO articles (url, source, created_at) VALUES (?, ?, ?)",
                ("https://old.com", "openai", "2025-01-01T00:00:00"),
            )
            conn.commit()

        deleted = purge_old_articles(db_path, days=30)
        assert deleted == 1
        assert get_article(db_path, "https://old.com") is None

    def test_purge_keeps_recent(self, db_path):
        save_article(db_path, {
            "url": "https://recent.com",
            "source": "openai",
        })
        deleted = purge_old_articles(db_path, days=30)
        assert deleted == 0
        assert get_article(db_path, "https://recent.com") is not None


# -- get_article_by_title_date ------------------------------------------------

class TestGetByTitleDate:
    def test_found(self, db_path):
        save_article(db_path, {
            "url": "https://example.com/1",
            "source": "gemini",
            "title": "Update",
            "published_at": "2026-03-01T00:00:00+00:00",
        })
        row = get_article_by_title_date(db_path, "Update", "2026-03-01T00:00:00+00:00")
        assert row is not None
        assert row["url"] == "https://example.com/1"

    def test_not_found(self, db_path):
        assert get_article_by_title_date(db_path, "Missing", "2026-01-01") is None
