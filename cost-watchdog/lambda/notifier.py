"""
Notifier module - delivers formatted alerts to a configured Slack webhook URL.
"""

import logging
import os

try:
    import requests
except ImportError:
    # In Lambda, requests is in vendor/
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))
    import requests

logger = logging.getLogger(__name__)


def send_slack_alert(payload: dict) -> None:
    """
    POSTs payload as JSON to the configured SLACK_WEBHOOK_URL.

    Raises:
        RuntimeError: If SLACK_WEBHOOK_URL is not configured, webhook returns non-200,
                      or a network/timeout error occurs.
        ValueError: If SLACK_WEBHOOK_URL is not a valid HTTPS URL.
    """
    # 1. Read webhook URL from environment
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()

    # 2. Validate URL is set
    if not webhook_url:
        logger.error("SLACK_WEBHOOK_URL is not configured")
        raise RuntimeError("SLACK_WEBHOOK_URL is not configured")

    # 3. Validate URL is HTTPS
    if not webhook_url.startswith("https://"):
        logger.error("SLACK_WEBHOOK_URL is not a valid HTTPS URL")
        raise ValueError("SLACK_WEBHOOK_URL is not a valid HTTPS URL")

    # 4. POST payload to webhook
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
    except requests.exceptions.Timeout:
        logger.error("Slack webhook timed out after 5 seconds")
        raise RuntimeError("Slack webhook timed out")
    except requests.exceptions.ConnectionError as e:
        logger.error("Slack webhook connection failed: %s", str(e))
        raise RuntimeError("Slack webhook connection failed")
    except requests.exceptions.RequestException as e:
        logger.error("Slack webhook request failed: %s", str(e))
        raise RuntimeError(f"Slack webhook request failed: {e}")

    # 5. Check response status
    if response.status_code != 200:
        logger.error(
            "Slack webhook returned status %d: %s",
            response.status_code,
            response.text,
        )
        raise RuntimeError(f"Slack webhook returned status {response.status_code}")
