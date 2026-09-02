"""Unit tests for the notifier module."""

import pytest
from unittest.mock import patch, MagicMock
from notifier import send_slack_alert


class TestSendSlackAlert:
    """Tests for Slack notification sending."""

    def test_missing_webhook_url_raises_runtime_error(self, monkeypatch):
        """Should raise RuntimeError when SLACK_WEBHOOK_URL is not configured."""
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        with pytest.raises(RuntimeError, match="not configured"):
            send_slack_alert({"text": "test"})

    def test_non_https_url_raises_value_error(self, monkeypatch):
        """Should raise ValueError when SLACK_WEBHOOK_URL is not HTTPS."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "http://hooks.slack.com/services/T/B/X")
        with pytest.raises(ValueError, match="not a valid HTTPS URL"):
            send_slack_alert({"text": "test"})

    @patch("notifier.requests.post")
    def test_successful_post(self, mock_post, monkeypatch):
        """Should POST payload to webhook and succeed on 200 response."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        payload = {"text": "test alert"}
        send_slack_alert(payload)

        mock_post.assert_called_once_with(
            "https://hooks.slack.com/services/T/B/X",
            json=payload,
            timeout=5,
        )

    @patch("notifier.requests.post")
    def test_non_200_response_raises_runtime_error(self, mock_post, monkeypatch):
        """Should raise RuntimeError when webhook returns non-200."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "invalid_token"
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="status 403"):
            send_slack_alert({"text": "test"})

    @patch("notifier.requests.post")
    def test_timeout_raises_runtime_error(self, mock_post, monkeypatch):
        """Should raise RuntimeError on network timeout."""
        import requests as req
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
        mock_post.side_effect = req.exceptions.Timeout("Connection timed out")

        with pytest.raises(RuntimeError, match="timed out"):
            send_slack_alert({"text": "test"})
