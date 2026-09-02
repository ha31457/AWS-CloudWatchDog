"""Shared test configuration and fixtures for AWS Cost Watchdog tests."""

import json
import os
import sys
from pathlib import Path

import pytest

# Add the lambda directory to sys.path so tests can import modules directly
sys.path.insert(0, str(Path(__file__).parent.parent / "lambda"))

# Fixtures directory path
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def load_fixture():
    """Return a helper function that loads a JSON fixture file."""
    def _load(filename: str) -> dict:
        filepath = FIXTURES_DIR / filename
        with open(filepath, "r") as f:
            return json.load(f)
    return _load


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Ensure a clean environment for each test.

    Removes environment variables that modules depend on so tests
    start from a known state.
    """
    env_vars_to_clear = [
        "SLACK_WEBHOOK_URL",
        "SNS_TOPIC_ARN",
        "INR_RATE",
        "WATCHED_REGION",
    ]
    for var in env_vars_to_clear:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sample_resource_info():
    """Return a sample resource_info dictionary for testing."""
    return {
        "resource_type": "EC2",
        "detail": "2x t3.medium",
        "region": "ap-south-1",
        "launched_by": "arn:aws:iam::123456789012:user/dev",
        "instance_type": "t3.medium",
        "instance_count": 2,
        "resource_id": "i-0abcdef1234567890",
    }


@pytest.fixture
def sample_cost_info():
    """Return a sample cost_info dictionary for testing."""
    return {
        "hourly_usd": 0.0864,
        "monthly_usd": 62.21,
        "hourly_inr": 7.26,
        "monthly_inr": 5225.64,
        "severity": "LOW",
    }
