"""Tests for app.utils module."""

from datetime import datetime, timezone

from app.utils import compute_hash, format_datetime, parse_datetime, sanitize_for_log, truncate_text


class TestComputeHash:
    def test_deterministic(self):
        assert compute_hash("hello") == compute_hash("hello")

    def test_different_input_different_hash(self):
        assert compute_hash("a") != compute_hash("b")

    def test_empty_string(self):
        h = compute_hash("")
        assert isinstance(h, str) and len(h) == 64  # SHA256 hex length


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("hi", 10) == "hi"

    def test_long_text_truncated(self):
        result = truncate_text("abcdefghij", 7)
        assert result == "abcd..."
        assert len(result) == 7

    def test_exact_length_unchanged(self):
        assert truncate_text("abc", 3) == "abc"


class TestFormatDatetime:
    def test_none_returns_empty(self):
        assert format_datetime(None) == ""

    def test_utc_datetime(self):
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = format_datetime(dt)
        assert "2026-01-15" in result


class TestParseDatetime:
    def test_iso_format(self):
        dt = parse_datetime("2026-01-15T12:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_z_suffix(self):
        dt = parse_datetime("2026-01-15T12:00:00Z")
        assert dt is not None

    def test_empty_returns_none(self):
        assert parse_datetime("") is None

    def test_invalid_returns_none(self):
        assert parse_datetime("not-a-date") is None


class TestSanitizeForLog:
    def test_masks_openai_key(self):
        text = "key is sk-abc123def456ghi789jkl012mno"
        result = sanitize_for_log(text)
        assert "sk-abc123" not in result
        assert "sk-****" in result

    def test_no_sensitive_data_unchanged(self):
        text = "just a normal log line"
        assert sanitize_for_log(text) == text
