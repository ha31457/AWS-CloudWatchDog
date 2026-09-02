"""
Resource Parser module for AWS Cost Watchdog.

Extracts structured resource metadata from raw CloudTrail event detail objects
for EC2 RunInstances, RDS CreateDBInstance, and Lambda CreateFunction events.
"""

import logging

logger = logging.getLogger(__name__)


def parse_ec2(detail: dict) -> dict:
    """
    Parse an EC2 RunInstances CloudTrail event detail.

    Extracts instance type, instance count, region, launched-by ARN,
    and the first instance ID from the response.

    Args:
        detail: The CloudTrail event detail dict.

    Returns:
        Structured dict with resource metadata.
    """
    request_params = detail.get("requestParameters") or {}
    response_elements = detail.get("responseElements") or {}
    user_identity = detail.get("userIdentity") or {}

    # Extract instance type
    instance_type = request_params.get("instanceType", "unknown") or "unknown"

    # Extract instance count from instancesSet.items[0].minCount
    instance_count = 1
    try:
        instances_set = request_params.get("instancesSet") or {}
        items = instances_set.get("items") or []
        if items and len(items) > 0:
            min_count = items[0].get("minCount")
            if min_count is not None and int(min_count) >= 1:
                instance_count = int(min_count)
    except (TypeError, ValueError, IndexError):
        logger.warning("Could not extract instance count, defaulting to 1")
        instance_count = 1

    # Extract region
    region = detail.get("awsRegion", "unknown") or "unknown"

    # Extract launched_by (IAM ARN)
    launched_by = user_identity.get("arn", "unknown") or "unknown"

    # Extract resource_id (first instance ID from responseElements)
    resource_id = "unknown"
    try:
        resp_instances_set = response_elements.get("instancesSet") or {}
        resp_items = resp_instances_set.get("items") or []
        if resp_items and len(resp_items) > 0:
            resource_id = resp_items[0].get("instanceId", "unknown") or "unknown"
    except (TypeError, IndexError):
        logger.warning("Could not extract instance ID from response, defaulting to 'unknown'")

    # Build detail string
    detail_str = f"{instance_count}x {instance_type}"

    return {
        "resource_type": "EC2",
        "detail": detail_str,
        "region": region,
        "launched_by": launched_by,
        "instance_type": instance_type,
        "instance_count": instance_count,
        "resource_id": resource_id,
    }


def parse_rds(detail: dict) -> dict:
    """
    Parse an RDS CreateDBInstance CloudTrail event detail.

    Extracts DB instance class, engine, identifier, region, and launched-by ARN.

    Args:
        detail: The CloudTrail event detail dict.

    Returns:
        Structured dict with resource metadata.
    """
    request_params = detail.get("requestParameters") or {}
    user_identity = detail.get("userIdentity") or {}

    # Extract fields
    db_instance_class = request_params.get("dBInstanceClass", "unknown") or "unknown"
    engine = request_params.get("engine", "unknown") or "unknown"
    db_instance_identifier = request_params.get("dBInstanceIdentifier", "unknown") or "unknown"

    # Extract region
    region = detail.get("awsRegion", "unknown") or "unknown"

    # Extract launched_by (IAM ARN)
    launched_by = user_identity.get("arn", "unknown") or "unknown"

    # Build detail string
    detail_str = f"{db_instance_identifier} ({engine}, {db_instance_class})"

    return {
        "resource_type": "RDS",
        "detail": detail_str,
        "region": region,
        "launched_by": launched_by,
        "instance_type": db_instance_class,
        "instance_count": 1,
        "resource_id": db_instance_identifier,
    }


def parse_lambda(detail: dict) -> dict:
    """
    Parse a Lambda CreateFunction20150331 CloudTrail event detail.

    Extracts function name, memory size, region, and launched-by ARN.

    Args:
        detail: The CloudTrail event detail dict.

    Returns:
        Structured dict with resource metadata.
    """
    request_params = detail.get("requestParameters") or {}
    user_identity = detail.get("userIdentity") or {}

    # Extract fields
    function_name = request_params.get("functionName", "unknown") or "unknown"

    # Extract memory size, default to "unknown" if missing
    memory_size = request_params.get("memorySize")
    if memory_size is None:
        memory_size_str = "unknown"
    else:
        memory_size_str = str(memory_size)

    # Extract region
    region = detail.get("awsRegion", "unknown") or "unknown"

    # Extract launched_by (IAM ARN)
    launched_by = user_identity.get("arn", "unknown") or "unknown"

    # Build detail string
    detail_str = f"{function_name} ({memory_size_str}MB)"

    return {
        "resource_type": "Lambda",
        "detail": detail_str,
        "region": region,
        "launched_by": launched_by,
        "instance_type": memory_size_str,
        "instance_count": 1,
        "resource_id": function_name,
    }


def parse_event(detail: dict, event_name: str) -> dict:
    """
    Dispatch to the appropriate per-service parser based on event_name.

    Args:
        detail: The CloudTrail event detail dict.
        event_name: The CloudTrail eventName string.

    Returns:
        Structured resource metadata dict, or None for unsupported events.
    """
    parsers = {
        "RunInstances": parse_ec2,
        "CreateDBInstance": parse_rds,
        "CreateFunction20150331": parse_lambda,
    }

    parser = parsers.get(event_name)
    if parser is None:
        logger.warning(f"Unsupported event name: {event_name}")
        return None

    return parser(detail)
