"""
Cost Calculator module for AWS Cost Watchdog.

Contains static pricing tables for EC2 and RDS instance types (ap-south-1 region,
on-demand pricing) and default constants used for cost estimation.
"""

import logging
import os

logger = logging.getLogger(__name__)

# EC2 on-demand hourly prices in USD for ap-south-1 region
EC2_PRICES: dict[str, float] = {
    "t2.micro": 0.0116,
    "t2.small": 0.023,
    "t2.medium": 0.0464,
    "t3.micro": 0.0108,
    "t3.small": 0.0216,
    "t3.medium": 0.0432,
    "t3.large": 0.0864,
    "t3.xlarge": 0.1728,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "r5.large": 0.126,
    "p3.2xlarge": 3.06,
    "p4d.24xlarge": 32.77,
}

# RDS on-demand hourly prices in USD for ap-south-1 region
RDS_PRICES: dict[str, float] = {
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.m5.large": 0.171,
    "db.m5.xlarge": 0.342,
    "db.r5.large": 0.24,
}

# Default hourly price for unknown EC2 instance types
DEFAULT_EC2_PRICE: float = 0.10

# Default hourly price for unknown RDS instance classes
DEFAULT_RDS_PRICE: float = 0.20

# Default USD to INR conversion rate
DEFAULT_INR_RATE: float = 84


def get_inr_rate() -> float:
    """
    Read INR_RATE from environment variable, validate it is numeric and positive.
    Falls back to DEFAULT_INR_RATE (84) if not set or invalid.
    """
    inr_rate_str = os.environ.get("INR_RATE")
    if inr_rate_str is None:
        return DEFAULT_INR_RATE

    try:
        rate = float(inr_rate_str)
        if rate <= 0:
            logger.warning(
                "INR_RATE environment variable is non-positive (%s), using default %s",
                inr_rate_str,
                DEFAULT_INR_RATE,
            )
            return DEFAULT_INR_RATE
        return rate
    except (ValueError, TypeError):
        logger.warning(
            "INR_RATE environment variable is non-numeric (%s), using default %s",
            inr_rate_str,
            DEFAULT_INR_RATE,
        )
        return DEFAULT_INR_RATE


def get_severity(hourly_usd: float) -> str:
    """
    Classify severity based on hourly USD cost.

    LOW:    0 <= hourly_usd < 0.10
    MEDIUM: 0.10 <= hourly_usd <= 1.00
    HIGH:   hourly_usd > 1.00
    """
    if hourly_usd is None or not isinstance(hourly_usd, (int, float)) or hourly_usd < 0:
        logger.warning(
            "Cannot classify severity for hourly_usd=%s, defaulting to MEDIUM",
            hourly_usd,
        )
        return "MEDIUM"

    if hourly_usd < 0.10:
        return "LOW"
    elif hourly_usd <= 1.00:
        return "MEDIUM"
    else:
        return "HIGH"


def calculate_cost(resource_type: str, instance_type: str, instance_count: int = 1) -> dict:
    """
    Compute hourly/monthly costs in USD and INR with severity classification.

    Args:
        resource_type: "EC2", "RDS", or "Lambda"
        instance_type: The instance type/class string for pricing lookup
        instance_count: Number of instances (EC2 only, defaults to 1)

    Returns:
        dict with keys: hourly_usd, monthly_usd, hourly_inr, monthly_inr, severity
    """
    # Default instance_count to 1 if invalid
    if not isinstance(instance_count, int) or instance_count < 1:
        instance_count = 1

    # Lookup per-instance hourly price
    if resource_type == "EC2":
        if instance_type in EC2_PRICES:
            per_instance_price = EC2_PRICES[instance_type]
        else:
            logger.warning(
                "Unknown EC2 instance type '%s', using default price $%s/hr",
                instance_type,
                DEFAULT_EC2_PRICE,
            )
            per_instance_price = DEFAULT_EC2_PRICE
    elif resource_type == "RDS":
        if instance_type in RDS_PRICES:
            per_instance_price = RDS_PRICES[instance_type]
        else:
            logger.warning(
                "Unknown RDS instance class '%s', using default price $%s/hr",
                instance_type,
                DEFAULT_RDS_PRICE,
            )
            per_instance_price = DEFAULT_RDS_PRICE
    elif resource_type == "Lambda":
        # Lambda cost is compute-time based, not instance-based
        per_instance_price = 0.00
    else:
        logger.warning(
            "Unknown resource type '%s', defaulting to MEDIUM severity with $0.00 cost",
            resource_type,
        )
        per_instance_price = 0.00

    # Compute total hourly cost
    hourly_usd = per_instance_price * instance_count

    # Round hourly to 4 decimal places
    hourly_usd = round(hourly_usd, 4)

    # Compute monthly cost: hourly * 24 * 30, rounded to 2 decimal places
    monthly_usd = round(hourly_usd * 24 * 30, 2)

    # Convert to INR
    inr_rate = get_inr_rate()
    hourly_inr = round(hourly_usd * inr_rate, 2)
    monthly_inr = round(monthly_usd * inr_rate, 2)

    # Determine severity
    severity = get_severity(hourly_usd)

    return {
        "hourly_usd": hourly_usd,
        "monthly_usd": monthly_usd,
        "hourly_inr": hourly_inr,
        "monthly_inr": monthly_inr,
        "severity": severity,
    }
