"""Unit tests for the alert_builder module."""

import pytest
from alert_builder import (
    build_kill_switch_url,
    build_slack_payload,
    SEVERITY_COLORS,
    SEVERITY_EMOJIS,
)


class TestBuildKillSwitchUrl:
    """Tests for kill-switch URL generation."""

    def test_ec2_url_contains_region(self):
        """EC2 kill-switch URL should contain the correct region."""
        url = build_kill_switch_url("EC2", "ap-south-1", "i-0abc123")
        assert "ap-south-1" in url
        assert "ec2" in url

    def test_rds_url_contains_db_identifier(self):
        """RDS kill-switch URL should contain the DB identifier."""
        url = build_kill_switch_url("RDS", "ap-south-1", "my-test-db")
        assert "my-test-db" in url
        assert "rds" in url

    def test_lambda_url_contains_function_name(self):
        """Lambda kill-switch URL should contain the function name."""
        url = build_kill_switch_url("Lambda", "ap-south-1", "my-test-function")
        assert "my-test-function" in url
        assert "lambda" in url

    def test_url_max_length(self):
        """URL should never exceed 2048 characters."""
        long_id = "a" * 3000
        url = build_kill_switch_url("EC2", "ap-south-1", long_id)
        assert len(url) <= 2048

    def test_special_characters_encoded(self):
        """Special characters in resource_id should be URL-encoded."""
        url = build_kill_switch_url("RDS", "us-east-1", "db/test&name")
        # The special chars should be encoded
        assert "db/test&name" not in url  # raw chars should not appear
        assert "us-east-1" in url


class TestBuildSlackPayload:
    """Tests for Slack payload construction."""

    def test_payload_contains_all_required_fields(self, sample_resource_info, sample_cost_info):
        """Slack payload should contain all required fields."""
        payload = build_slack_payload(sample_resource_info, sample_cost_info)

        # Verify structure
        assert "attachments" in payload
        attachment = payload["attachments"][0]
        assert "color" in attachment
        assert "blocks" in attachment

        # Find the section block with fields
        blocks = attachment["blocks"]
        section = next(b for b in blocks if b["type"] == "section")
        fields_text = " ".join(f["text"] for f in section["fields"])

        # Verify all required fields are present
        assert "Resource Type" in fields_text
        assert "EC2" in fields_text
        assert "Details" in fields_text
        assert "Region" in fields_text
        assert "ap-south-1" in fields_text
        assert "Launched By" in fields_text
        assert "Hourly Cost" in fields_text
        assert "Monthly Cost" in fields_text
        assert "Severity" in fields_text

    def test_payload_contains_kill_switch_button(self, sample_resource_info, sample_cost_info):
        """Payload should contain an actions block with a kill-switch button."""
        payload = build_slack_payload(sample_resource_info, sample_cost_info)
        blocks = payload["attachments"][0]["blocks"]
        actions = next(b for b in blocks if b["type"] == "actions")
        button = actions["elements"][0]

        assert button["type"] == "button"
        assert button["text"]["text"] == "Kill Resource"
        assert "url" in button
        assert button["style"] == "danger"

    def test_color_mapping_high(self, sample_resource_info):
        """HIGH severity should map to 'danger' color."""
        cost_info = {"hourly_usd": 5.0, "monthly_usd": 3600.0,
                     "hourly_inr": 420.0, "monthly_inr": 302400.0, "severity": "HIGH"}
        payload = build_slack_payload(sample_resource_info, cost_info)
        assert payload["attachments"][0]["color"] == "danger"

    def test_color_mapping_medium(self, sample_resource_info):
        """MEDIUM severity should map to 'warning' color."""
        cost_info = {"hourly_usd": 0.5, "monthly_usd": 360.0,
                     "hourly_inr": 42.0, "monthly_inr": 30240.0, "severity": "MEDIUM"}
        payload = build_slack_payload(sample_resource_info, cost_info)
        assert payload["attachments"][0]["color"] == "warning"

    def test_color_mapping_low(self, sample_resource_info):
        """LOW severity should map to 'good' color."""
        cost_info = {"hourly_usd": 0.05, "monthly_usd": 36.0,
                     "hourly_inr": 4.2, "monthly_inr": 3024.0, "severity": "LOW"}
        payload = build_slack_payload(sample_resource_info, cost_info)
        assert payload["attachments"][0]["color"] == "good"

    def test_severity_emojis_present(self, sample_resource_info, sample_cost_info):
        """Severity emoji should be present in the payload fields."""
        payload = build_slack_payload(sample_resource_info, sample_cost_info)
        blocks = payload["attachments"][0]["blocks"]
        section = next(b for b in blocks if b["type"] == "section")
        fields_text = " ".join(f["text"] for f in section["fields"])

        # LOW severity emoji (green circle)
        assert "\U0001f7e2" in fields_text or "LOW" in fields_text
