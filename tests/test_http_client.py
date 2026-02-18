"""Tests for app.sources.http_client module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.sources.http_client import (
    BACKOFF_BASE,
    DEFAULT_HEADERS,
    RSS_HEADERS,
    create_session,
    fetch_with_retry,
)


class TestCreateSession:
    def test_default_headers_applied(self):
        session = create_session()
        assert "User-Agent" in session.headers
        assert "br" not in session.headers.get("Accept-Encoding", "")

    def test_extra_headers_merged(self):
        session = create_session(extra_headers={"X-Custom": "test"})
        assert session.headers["X-Custom"] == "test"
        assert "User-Agent" in session.headers  # defaults still present

    def test_no_brotli_in_encoding(self):
        """Brotli caused binary responses; must never appear."""
        assert "br" not in DEFAULT_HEADERS["Accept-Encoding"]


class TestFetchWithRetry:
    @patch("app.sources.http_client.time.sleep")
    def test_success_on_first_try(self, mock_sleep):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        result = fetch_with_retry("https://example.com", session=mock_session)
        assert result.status_code == 200
        mock_sleep.assert_not_called()

    @patch("app.sources.http_client.time.sleep")
    def test_retries_on_500(self, mock_sleep):
        error_resp = MagicMock()
        error_resp.status_code = 500
        error_resp.headers = {}

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.side_effect = [error_resp, ok_resp]

        result = fetch_with_retry(
            "https://example.com", session=mock_session, max_retries=3
        )
        assert result.status_code == 200
        assert mock_session.get.call_count == 2

    @patch("app.sources.http_client.time.sleep")
    def test_retries_on_connection_error(self, mock_sleep):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.side_effect = [
            requests.ConnectionError("fail"),
            ok_resp,
        ]

        result = fetch_with_retry(
            "https://example.com", session=mock_session, max_retries=3
        )
        assert result.status_code == 200

    @patch("app.sources.http_client.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        mock_session = MagicMock()
        mock_session.get.side_effect = requests.ConnectionError("fail")

        with pytest.raises(requests.ConnectionError):
            fetch_with_retry(
                "https://example.com", session=mock_session, max_retries=2
            )
        assert mock_session.get.call_count == 2

    @patch("app.sources.http_client.time.sleep")
    def test_no_retry_on_4xx(self, mock_sleep):
        error_resp = MagicMock()
        error_resp.status_code = 404
        error_resp.raise_for_status.side_effect = requests.HTTPError("404")

        mock_session = MagicMock()
        mock_session.get.return_value = error_resp

        with pytest.raises(requests.HTTPError):
            fetch_with_retry(
                "https://example.com", session=mock_session, max_retries=3
            )
        # Should NOT retry on 4xx
        assert mock_session.get.call_count == 1

    @patch("app.sources.http_client.time.sleep")
    def test_retries_on_429_with_retry_after(self, mock_sleep):
        rate_resp = MagicMock()
        rate_resp.status_code = 429
        rate_resp.headers = {"Retry-After": "2"}

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status = MagicMock()

        mock_session = MagicMock()
        mock_session.get.side_effect = [rate_resp, ok_resp]

        result = fetch_with_retry(
            "https://example.com", session=mock_session, max_retries=3
        )
        assert result.status_code == 200
        mock_sleep.assert_called_once_with(2.0)
