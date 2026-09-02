"""
AWS Cost Watchdog Lambda Handler.

Entry point for the Lambda function invoked by EventBridge.
Orchestrates: Resource_Parser -> Cost_Calculator -> Alert_Builder -> Notifier
"""

import json
import logging
import os
import sys
import traceback

# Add vendor directory to sys.path for bundled dependencies
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from resource_parser import parse_event
from cost_calculator import calculate_cost
from alert_builder import build_slack_payload
from notifier import send_slack_alert

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Supported event names
SUPPORTED_EVENTS = {"RunInstances", "CreateDBInstance", "CreateFunction20150331"}


def lambda_handler(event: dict, context=None) -> dict:
    """
    Lambda entry point invoked by EventBridge.

    Flow:
    1. Log raw event
    2. Validate SLACK_WEBHOOK_URL is configured
    3. Extract event_name from event
    4. If unsupported event: return {"statusCode": 200, "body": "ignored"}
    5. Parse resource metadata
    6. Calculate cost
    7. Build Slack payload
    8. Send alert
    9. Return {"statusCode": 200, "body": "alert sent"}

    On any exception: log traceback, return {"statusCode": 500, "body": "processing error"}
    """
    # 1. Log the full raw event payload (Requirement 7.6)
    logger.info("Received event: %s", json.dumps(event))

    try:
        # 2. Validate SLACK_WEBHOOK_URL is configured (Requirement 7.3)
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            logger.error("SLACK_WEBHOOK_URL environment variable is missing or empty")
            return {"statusCode": 500, "body": "configuration error"}

        # 3. Extract event_name from event detail
        detail = event.get("detail") or {}
        event_name = detail.get("eventName", "")

        # Skip DryRun operations (console preflight checks)
        error_code = detail.get("errorCode", "")
        if error_code == "Client.DryRunOperation":
            logger.info("DryRun operation detected, skipping")
            return {"statusCode": 200, "body": "ignored"}

        # 4. If unsupported event: return ignored (Requirement 7.9)
        if event_name not in SUPPORTED_EVENTS:
            logger.info("Unsupported event name '%s', ignoring", event_name)
            return {"statusCode": 200, "body": "ignored"}

        # 5. Parse resource metadata
        resource_info = parse_event(detail, event_name)
        if resource_info is None:
            logger.warning("Resource parser returned None for event '%s'", event_name)
            return {"statusCode": 200, "body": "ignored"}

        logger.info(
            "Parsed resource: type=%s, detail=%s, region=%s",
            resource_info.get("resource_type"),
            resource_info.get("detail"),
            resource_info.get("region"),
        )

        # 6. Calculate cost
        cost_info = calculate_cost(
            resource_info["resource_type"],
            resource_info["instance_type"],
            resource_info["instance_count"],
        )

        logger.info(
            "Cost calculated: hourly=$%s, monthly=$%s, severity=%s",
            cost_info.get("hourly_usd"),
            cost_info.get("monthly_usd"),
            cost_info.get("severity"),
        )

        # 7. Build Slack payload
        payload = build_slack_payload(resource_info, cost_info)

        # 8. Send alert
        send_slack_alert(payload)

        # 9. Return success (Requirement 7.7)
        logger.info("Alert sent successfully for %s event", event_name)
        return {"statusCode": 200, "body": "alert sent"}

    except Exception as e:
        # Log full traceback and return processing error (Requirement 7.8)
        logger.error("Processing error: %s", str(e))
        logger.error("Traceback:\n%s", traceback.format_exc())
        return {"statusCode": 500, "body": "processing error"}
