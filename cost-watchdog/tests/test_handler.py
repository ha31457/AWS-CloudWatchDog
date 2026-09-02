"""Integration tests for the Lambda handler module."""

import pytest
from unittest.mock import patch, MagicMock
from handler import lambda_handler


class TestLambdaHandler:
    """Integration tests for the full Lambda handler pipeline."""

    @patch("handler.send_slack_alert")
    def test_full_ec2_event_pipeline(self, mock_send, monkeypatch, load_fixture):
        """Full EC2 event should parse, calculate cost, build alert, and send."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        event = load_fixture("ec2_run_instances.json")
        result = lambda_handler(event)

        assert result == {"statusCode": 200, "body": "alert sent"}
        mock_send.assert_called_once()

        # Verify the payload passed to send_slack_alert has expected structure
        payload = mock_send.call_args[0][0]
        assert "attachments" in payload

    def test_missing_webhook_returns_config_error(self, monkeypatch, load_fixture):
        """Missing SLACK_WEBHOOK_URL should return configuration error."""
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        event = load_fixture("ec2_run_instances.json")
        result = lambda_handler(event)

        assert result == {"statusCode": 500, "body": "configuration error"}

    @patch("handler.send_slack_alert")
    def test_unsupported_event_returns_ignored(self, mock_send, monkeypatch):
        """Unsupported eventName should return ignored without sending alert."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        event = {
            "detail": {
                "eventName": "TerminateInstances",
            }
        }
        result = lambda_handler(event)

        assert result == {"statusCode": 200, "body": "ignored"}
        mock_send.assert_not_called()

    @patch("handler.send_slack_alert")
    def test_rds_event_pipeline(self, mock_send, monkeypatch, load_fixture):
        """Full RDS event should process successfully."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        event = load_fixture("rds_create_db.json")
        result = lambda_handler(event)

        assert result == {"statusCode": 200, "body": "alert sent"}
        mock_send.assert_called_once()

    @patch("handler.send_slack_alert")
    def test_lambda_event_pipeline(self, mock_send, monkeypatch, load_fixture):
        """Full Lambda event should process successfully."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")

        event = load_fixture("lambda_create_function.json")
        result = lambda_handler(event)

        assert result == {"statusCode": 200, "body": "alert sent"}
        mock_send.assert_called_once()

    @patch("handler.send_slack_alert")
    def test_send_failure_returns_processing_error(self, mock_send, monkeypatch, load_fixture):
        """Exception during send should return processing error."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
        mock_send.side_effect = RuntimeError("webhook failed")

        event = load_fixture("ec2_run_instances.json")
        result = lambda_handler(event)

        assert result == {"statusCode": 500, "body": "processing error"}
