"""Unit tests for the cost_calculator module."""

import pytest
from cost_calculator import (
    calculate_cost,
    get_severity,
    get_inr_rate,
    EC2_PRICES,
    RDS_PRICES,
    DEFAULT_EC2_PRICE,
    DEFAULT_RDS_PRICE,
    DEFAULT_INR_RATE,
)


class TestGetSeverity:
    """Tests for severity boundary classification."""

    def test_low_severity_below_threshold(self):
        assert get_severity(0.099) == "LOW"

    def test_low_severity_zero(self):
        assert get_severity(0.0) == "LOW"

    def test_medium_severity_at_lower_boundary(self):
        assert get_severity(0.10) == "MEDIUM"

    def test_medium_severity_at_upper_boundary(self):
        assert get_severity(1.00) == "MEDIUM"

    def test_high_severity_above_threshold(self):
        assert get_severity(1.01) == "HIGH"

    def test_high_severity_large_value(self):
        assert get_severity(100.0) == "HIGH"


class TestCalculateCostEC2:
    """Tests for EC2 cost calculation."""

    def test_known_ec2_type_lookup(self):
        """t3.large should look up to 0.0864 per hour."""
        result = calculate_cost("EC2", "t3.large", 1)
        assert result["hourly_usd"] == 0.0864

    def test_unknown_ec2_type_defaults(self):
        """Unknown EC2 instance type should default to $0.10/hr."""
        result = calculate_cost("EC2", "x99.superlarge", 1)
        assert result["hourly_usd"] == DEFAULT_EC2_PRICE

    def test_instance_count_multiplication(self):
        """2x t3.medium (0.0432/hr each) = 0.0864/hr total."""
        result = calculate_cost("EC2", "t3.medium", 2)
        assert result["hourly_usd"] == 0.0864

    def test_monthly_cost_equals_hourly_times_720(self):
        """Monthly cost = hourly * 24 * 30 = hourly * 720."""
        result = calculate_cost("EC2", "t3.large", 1)
        expected_monthly = round(0.0864 * 24 * 30, 2)
        assert result["monthly_usd"] == expected_monthly

    def test_inr_conversion_with_default_rate(self):
        """INR conversion uses default rate of 84."""
        result = calculate_cost("EC2", "t3.large", 1)
        expected_hourly_inr = round(0.0864 * DEFAULT_INR_RATE, 2)
        assert result["hourly_inr"] == expected_hourly_inr

    def test_invalid_instance_count_defaults_to_one(self):
        """Invalid instance count should default to 1."""
        result = calculate_cost("EC2", "t3.large", -5)
        assert result["hourly_usd"] == 0.0864


class TestCalculateCostRDS:
    """Tests for RDS cost calculation."""

    def test_known_rds_class_lookup(self):
        """db.m5.large should look up to 0.171 per hour."""
        result = calculate_cost("RDS", "db.m5.large", 1)
        assert result["hourly_usd"] == 0.171

    def test_unknown_rds_class_defaults(self):
        """Unknown RDS instance class should default to $0.20/hr."""
        result = calculate_cost("RDS", "db.z99.mega", 1)
        assert result["hourly_usd"] == DEFAULT_RDS_PRICE


class TestCalculateCostLambda:
    """Tests for Lambda cost calculation."""

    def test_lambda_returns_zero_cost(self):
        """Lambda cost is compute-time based, returns 0 for hourly."""
        result = calculate_cost("Lambda", "256", 1)
        assert result["hourly_usd"] == 0.0
        assert result["monthly_usd"] == 0.0


class TestGetInrRate:
    """Tests for INR rate environment variable handling."""

    def test_default_rate_when_env_not_set(self):
        """Should return 84 when INR_RATE is not set."""
        assert get_inr_rate() == DEFAULT_INR_RATE

    def test_valid_env_rate(self, monkeypatch):
        """Should return the env value when it's a valid positive number."""
        monkeypatch.setenv("INR_RATE", "85.5")
        assert get_inr_rate() == 85.5

    def test_invalid_non_numeric_env_rate(self, monkeypatch):
        """Should fallback to 84 for non-numeric INR_RATE."""
        monkeypatch.setenv("INR_RATE", "not_a_number")
        assert get_inr_rate() == DEFAULT_INR_RATE

    def test_invalid_negative_env_rate(self, monkeypatch):
        """Should fallback to 84 for negative INR_RATE."""
        monkeypatch.setenv("INR_RATE", "-10")
        assert get_inr_rate() == DEFAULT_INR_RATE

    def test_invalid_zero_env_rate(self, monkeypatch):
        """Should fallback to 84 for zero INR_RATE."""
        monkeypatch.setenv("INR_RATE", "0")
        assert get_inr_rate() == DEFAULT_INR_RATE
