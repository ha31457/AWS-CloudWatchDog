"""
Alert Builder module for AWS Cost Watchdog.

Constructs Slack Block Kit message payloads with colour-coded severity,
resource metadata fields, and kill-switch console URLs for one-click
resource termination.
"""

import logging
import urllib.parse

logger = logging.getLogger(__name__)

# Severity to Slack attachment colour mapping
SEVERITY_COLORS = {
    "HIGH": "danger",
    "MEDIUM": "warning",
    "LOW": "good",
}

# Severity to emoji mapping
SEVERITY_EMOJIS = {
    "HIGH": "\U0001f534",      # 🔴
    "MEDIUM": "\U0001f7e1",    # 🟡
    "LOW": "\U0001f7e2",       # 🟢
}

# Kill-switch URL templates per resource type
KILL_SWITCH_TEMPLATES = {
    "EC2": "https://console.aws.amazon.com/ec2/v2/home?region={region}#Instances",
    "RDS": "https://console.aws.amazon.com/rds/home?region={region}#database:id={resource_id}",
    "Lambda": "https://console.aws.amazon.com/lambda/home?region={region}#/functions/{resource_id}",
}

# Maximum URL length per RFC/browser compatibility
MAX_URL_LENGTH = 2048


def build_kill_switch_url(resource_type: str, region: str, resource_id: str) -> str:
    """
    Generate an AWS Console deep-link URL for the given resource.

    Uses URL templates specific to each resource type. URL-encodes special
    characters in resource_id. Handles missing fields gracefully and ensures
    the final URL does not exceed 2048 characters.

    Args:
        resource_type: One of "EC2", "RDS", or "Lambda".
        region: The AWS region string (e.g. "ap-south-1").
        resource_id: The resource identifier (instance ID, DB name, function name).

    Returns:
        A URL string pointing to the resource's AWS Console page.
    """
    # Handle missing/empty region
    if not region or not isinstance(region, str):
        logger.warning("Missing or empty region for kill-switch URL, using empty string")
        region = ""

    # Handle missing/empty resource_id
    if not resource_id or not isinstance(resource_id, str):
        logger.warning("Missing or empty resource_id for kill-switch URL, using empty string")
        resource_id = ""

    # URL-encode resource_id to handle special characters
    encoded_resource_id = urllib.parse.quote(resource_id, safe="")

    # Get the template for this resource type, default to EC2 if unknown
    template = KILL_SWITCH_TEMPLATES.get(resource_type, KILL_SWITCH_TEMPLATES["EC2"])

    # Build the URL
    url = template.format(region=region, resource_id=encoded_resource_id)

    # Ensure URL is no longer than 2048 characters
    if len(url) > MAX_URL_LENGTH:
        # Truncate by shortening the encoded resource_id
        # Calculate how much we need to remove
        excess = len(url) - MAX_URL_LENGTH
        if len(encoded_resource_id) > excess:
            truncated_id = encoded_resource_id[: len(encoded_resource_id) - excess]
            url = template.format(region=region, resource_id=truncated_id)
        else:
            # Resource ID is too short to truncate meaningfully, use empty
            url = template.format(region=region, resource_id="")

        logger.warning(
            "Kill-switch URL truncated to %d characters (was %d)",
            len(url),
            len(url) + excess,
        )

    return url


def build_slack_payload(resource_info: dict, cost_info: dict) -> dict:
    """
    Construct a Slack Block Kit attachment payload for a cost alert.

    Builds a message with a colour-coded attachment containing a header,
    resource/cost fields section, and a kill-switch action button.

    Args:
        resource_info: Dict with keys: resource_type, detail, region,
                       launched_by, resource_id.
        cost_info: Dict with keys: hourly_usd, monthly_usd, hourly_inr,
                   monthly_inr, severity.

    Returns:
        Dict ready for JSON serialization and POST to Slack webhook.
    """
    # Extract values with safe defaults
    resource_type = resource_info.get("resource_type", "unknown")
    detail = resource_info.get("detail", "unknown")
    region = resource_info.get("region", "unknown")
    launched_by = resource_info.get("launched_by", "unknown")
    resource_id = resource_info.get("resource_id", "unknown")

    hourly_usd = cost_info.get("hourly_usd", 0.0)
    monthly_usd = cost_info.get("monthly_usd", 0.0)
    hourly_inr = cost_info.get("hourly_inr", 0.0)
    monthly_inr = cost_info.get("monthly_inr", 0.0)
    severity = cost_info.get("severity", "MEDIUM")

    # Map severity to colour and emoji
    color = SEVERITY_COLORS.get(severity, "warning")
    emoji = SEVERITY_EMOJIS.get(severity, "\U0001f7e1")

    # Format monetary values with commas for INR
    hourly_cost_str = f"${hourly_usd} (~\u20b9{hourly_inr})"
    monthly_cost_str = f"${monthly_usd} (~\u20b9{monthly_inr:,.2f})"

    # Build kill-switch URL
    kill_switch_url = build_kill_switch_url(resource_type, region, resource_id)

    # Header block
    header_block = {
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "\U0001f6a8 AWS Cost Watchdog Alert",
        },
    }

    # Section block with fields
    section_block = {
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*Resource Type:*\n{resource_type}"},
            {"type": "mrkdwn", "text": f"*Details:*\n{detail}"},
            {"type": "mrkdwn", "text": f"*Region:*\n{region}"},
            {"type": "mrkdwn", "text": f"*Launched By:*\n{launched_by}"},
            {"type": "mrkdwn", "text": f"*Hourly Cost:*\n{hourly_cost_str}"},
            {"type": "mrkdwn", "text": f"*Monthly Cost:*\n{monthly_cost_str}"},
            {"type": "mrkdwn", "text": f"*Severity:*\n{emoji} {severity}"},
        ],
    }

    # Actions block with kill-switch button
    actions_block = {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Kill Resource",
                },
                "url": kill_switch_url,
                "style": "danger",
            }
        ],
    }

    # Assemble the full payload
    payload = {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    header_block,
                    section_block,
                    actions_block,
                ],
            }
        ]
    }

    return payload
