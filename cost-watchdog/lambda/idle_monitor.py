"""
Idle Resource Monitor for AWS Cost Watchdog.

Runs on a 15-minute schedule via EventBridge. Checks CPU utilization
of all running EC2 instances and alerts on underutilized resources.
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

import boto3

from cost_calculator import calculate_cost, EC2_PRICES, DEFAULT_EC2_PRICE
from alert_builder import build_kill_switch_url, SEVERITY_EMOJIS
from notifier import send_slack_alert

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# CPU threshold percentage - below this is considered idle
CPU_THRESHOLD = 5.0


def get_running_instances(ec2_client) -> list:
    """Get all running EC2 instances in the region."""
    response = ec2_client.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    instances = []
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            instances.append(instance)
    return instances


def get_cpu_utilization(cloudwatch_client, instance_id: str) -> float | None:
    """
    Get average CPU utilization for an instance over the last 15 minutes.
    Returns None if no data points available.
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=15)

    response = cloudwatch_client.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start_time,
        EndTime=end_time,
        Period=900,  # 15 minutes
        Statistics=["Average"],
    )

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None

    # Return the average of all datapoints
    avg_cpu = sum(dp["Average"] for dp in datapoints) / len(datapoints)
    return round(avg_cpu, 2)


def get_instance_name(instance: dict) -> str:
    """Extract the Name tag from an instance, or return 'unnamed'."""
    tags = instance.get("Tags") or []
    for tag in tags:
        if tag.get("Key") == "Name":
            return tag.get("Value", "unnamed")
    return "unnamed"


def build_idle_alert_payload(instance: dict, cpu_avg: float, region: str) -> dict:
    """Build a Slack payload for an idle instance alert."""
    instance_id = instance["InstanceId"]
    instance_type = instance.get("InstanceType", "unknown")
    instance_name = get_instance_name(instance)
    launch_time = instance.get("LaunchTime")
    
    # Calculate how long it's been running
    if launch_time:
        if isinstance(launch_time, str):
            launch_dt = datetime.fromisoformat(launch_time.replace("Z", "+00:00"))
        else:
            launch_dt = launch_time
        running_duration = datetime.now(timezone.utc) - launch_dt
        hours_running = round(running_duration.total_seconds() / 3600, 1)
        running_str = f"{hours_running} hours"
    else:
        running_str = "unknown"

    # Get cost info
    hourly_price = EC2_PRICES.get(instance_type, DEFAULT_EC2_PRICE)
    cost_info = calculate_cost("EC2", instance_type, 1)
    
    # Build kill-switch URL
    kill_url = build_kill_switch_url("EC2", region, instance_id)

    # Build Slack payload
    payload = {
        "attachments": [
            {
                "color": "warning",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "\u26a0\ufe0f Idle Resource Detected",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Instance:*\n{instance_name} ({instance_id})"},
                            {"type": "mrkdwn", "text": f"*Type:*\n{instance_type}"},
                            {"type": "mrkdwn", "text": f"*Region:*\n{region}"},
                            {"type": "mrkdwn", "text": f"*Running For:*\n{running_str}"},
                            {"type": "mrkdwn", "text": f"*CPU Usage:*\n{cpu_avg}% (threshold: {CPU_THRESHOLD}%)"},
                            {"type": "mrkdwn", "text": f"*Wasted Cost:*\n${cost_info['hourly_usd']}/hr (~\u20b9{cost_info['hourly_inr']}/hr)"},
                            {"type": "mrkdwn", "text": f"*Monthly Waste:*\n${cost_info['monthly_usd']}/mo (~\u20b9{cost_info['monthly_inr']}/mo)"},
                        ],
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "Stop Instance"},
                                "url": kill_url,
                                "style": "danger",
                            }
                        ],
                    },
                ],
            }
        ]
    }
    return payload


def lambda_handler(event: dict, context=None) -> dict:
    """
    Idle monitor Lambda entry point.
    Triggered every 15 minutes by EventBridge scheduled rule.
    """
    logger.info("Idle monitor triggered: %s", json.dumps(event))

    try:
        # Validate configuration
        webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        if not webhook_url:
            logger.error("SLACK_WEBHOOK_URL not configured")
            return {"statusCode": 500, "body": "configuration error"}

        region = os.environ.get("WATCHED_REGION", "ap-south-1")

        # Initialize AWS clients
        ec2_client = boto3.client("ec2", region_name=region)
        cloudwatch_client = boto3.client("cloudwatch", region_name=region)

        # Get all running instances
        instances = get_running_instances(ec2_client)
        logger.info("Found %d running instances", len(instances))

        if not instances:
            return {"statusCode": 200, "body": "no running instances"}

        idle_count = 0
        for instance in instances:
            instance_id = instance["InstanceId"]
            
            # Check CPU utilization
            cpu_avg = get_cpu_utilization(cloudwatch_client, instance_id)

            if cpu_avg is None:
                logger.info("No CPU data for %s (may be newly launched), skipping", instance_id)
                continue

            logger.info("Instance %s: CPU avg = %.2f%%", instance_id, cpu_avg)

            if cpu_avg < CPU_THRESHOLD:
                logger.info("Instance %s is IDLE (CPU %.2f%% < %.2f%%)", instance_id, cpu_avg, CPU_THRESHOLD)
                
                # Build and send idle alert
                payload = build_idle_alert_payload(instance, cpu_avg, region)
                send_slack_alert(payload)
                idle_count += 1

        logger.info("Idle monitor complete: %d idle instances alerted", idle_count)
        return {"statusCode": 200, "body": f"{idle_count} idle alerts sent"}

    except Exception as e:
        logger.error("Idle monitor error: %s", str(e))
        logger.error("Traceback:\n%s", __import__('traceback').format_exc())
        return {"statusCode": 500, "body": "processing error"}
