"""Unit tests for the resource_parser module."""

import pytest
from resource_parser import parse_event, parse_ec2, parse_rds, parse_lambda


class TestParseEC2:
    """Tests for EC2 RunInstances event parsing."""

    def test_ec2_parsing_from_fixture(self, load_fixture):
        """Parse EC2 fixture: correct type, count, region, ARN."""
        event = load_fixture("ec2_run_instances.json")
        detail = event["detail"]
        result = parse_event(detail, "RunInstances")

        assert result["resource_type"] == "EC2"
        assert result["instance_type"] == "t3.medium"
        assert result["instance_count"] == 2
        assert result["region"] == "ap-south-1"
        assert result["launched_by"] == "arn:aws:iam::123456789012:user/dev-user"
        assert result["resource_id"] == "i-0abc123def456ghi7"
        assert result["detail"] == "2x t3.medium"


class TestParseRDS:
    """Tests for RDS CreateDBInstance event parsing."""

    def test_rds_parsing_from_fixture(self, load_fixture):
        """Parse RDS fixture: correct class, engine, region, ARN."""
        event = load_fixture("rds_create_db.json")
        detail = event["detail"]
        result = parse_event(detail, "CreateDBInstance")

        assert result["resource_type"] == "RDS"
        assert result["instance_type"] == "db.m5.large"
        assert result["instance_count"] == 1
        assert result["region"] == "ap-south-1"
        assert result["launched_by"] == "arn:aws:iam::123456789012:user/dev-user"
        assert result["resource_id"] == "my-test-db"
        assert "mysql" in result["detail"]
        assert "db.m5.large" in result["detail"]


class TestParseLambda:
    """Tests for Lambda CreateFunction event parsing."""

    def test_lambda_parsing_from_fixture(self, load_fixture):
        """Parse Lambda fixture: correct function name, memory, region, ARN."""
        event = load_fixture("lambda_create_function.json")
        detail = event["detail"]
        result = parse_event(detail, "CreateFunction20150331")

        assert result["resource_type"] == "Lambda"
        assert result["instance_type"] == "256"
        assert result["instance_count"] == 1
        assert result["region"] == "ap-south-1"
        assert result["launched_by"] == "arn:aws:iam::123456789012:user/dev-user"
        assert result["resource_id"] == "my-test-function"
        assert "my-test-function" in result["detail"]
        assert "256MB" in result["detail"]


class TestMissingFields:
    """Tests for missing field substitution with 'unknown'."""

    def test_missing_instance_type(self):
        """Missing instanceType should be substituted with 'unknown'."""
        detail = {
            "requestParameters": {},
            "responseElements": {},
            "userIdentity": {},
            "awsRegion": "ap-south-1",
        }
        result = parse_ec2(detail)
        assert result["instance_type"] == "unknown"

    def test_missing_region(self):
        """Missing awsRegion should be substituted with 'unknown'."""
        detail = {
            "requestParameters": {"instanceType": "t3.medium"},
            "responseElements": {},
            "userIdentity": {},
        }
        result = parse_ec2(detail)
        assert result["region"] == "unknown"

    def test_missing_user_identity_arn(self):
        """Missing userIdentity.arn should be substituted with 'unknown'."""
        detail = {
            "requestParameters": {"instanceType": "t3.medium"},
            "responseElements": {},
            "userIdentity": {},
            "awsRegion": "ap-south-1",
        }
        result = parse_ec2(detail)
        assert result["launched_by"] == "unknown"

    def test_completely_empty_detail(self):
        """Completely empty detail dict should not raise, returns 'unknown' fields."""
        result = parse_ec2({})
        assert result["resource_type"] == "EC2"
        assert result["instance_type"] == "unknown"
        assert result["region"] == "unknown"
        assert result["launched_by"] == "unknown"
        assert result["instance_count"] == 1

    def test_rds_missing_fields(self):
        """RDS with missing fields should substitute 'unknown'."""
        result = parse_rds({})
        assert result["resource_type"] == "RDS"
        assert result["instance_type"] == "unknown"
        assert result["region"] == "unknown"
        assert result["resource_id"] == "unknown"

    def test_lambda_missing_fields(self):
        """Lambda with missing fields should substitute 'unknown'."""
        result = parse_lambda({})
        assert result["resource_type"] == "Lambda"
        assert result["region"] == "unknown"
        assert result["resource_id"] == "unknown"


class TestUnsupportedEvent:
    """Tests for unsupported event names."""

    def test_unsupported_event_returns_none(self):
        """Unsupported event_name should return None."""
        result = parse_event({"eventName": "TerminateInstances"}, "TerminateInstances")
        assert result is None

    def test_empty_event_name_returns_none(self):
        """Empty event_name should return None."""
        result = parse_event({}, "")
        assert result is None
