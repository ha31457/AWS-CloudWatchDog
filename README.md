# AWS Cost Watchdog

**Event-driven serverless alerting that detects cost-impacting AWS resource launches and delivers Slack notifications within 60 seconds.**

Stop surprise billing before it starts. AWS Cost Watchdog monitors your account in real time and alerts you the moment someone launches an expensive resource, not 24-48 hours later when Cost Explorer finally updates.

---

## Architecture

```
┌─────────────┐     ┌────────────┐     ┌──────────────────┐     ┌──────────────┐     ┌───────────┐
│ AWS Account │────>│ CloudTrail │────>│  EventBridge Rule │────>│    Lambda    │────>│   Slack   │
│ (EC2/RDS/   │     │ (Mgmt      │     │  (RunInstances,   │     │ cost-watchdog│     │  Webhook  │
│  Lambda)    │     │  Write Evts)│     │   CreateDBInst,   │     │              │     │           │
└─────────────┘     └────────────┘     │   CreateFunc)     │     │ ┌──────────┐ │     └───────────┘
                                        └──────────────────┘     │ │ Resource │ │
                                                                  │ │  Parser  │ │
                                                                  │ └────┬─────┘ │
                                                                  │      │       │
                                                                  │ ┌────▼─────┐ │
                                                                  │ │   Cost   │ │
                                                                  │ │   Calc   │ │
                                                                  │ └────┬─────┘ │
                                                                  │      │       │
                                                                  │ ┌────▼─────┐ │
                                                                  │ │  Alert   │ │
                                                                  │ │ Builder  │ │
                                                                  │ └────┬─────┘ │
                                                                  │      │       │
                                                                  │ ┌────▼─────┐ │
                                                                  │ │ Notifier │ │
                                                                  │ └──────────┘ │
                                                                  └──────────────┘
```

**Flow:** A developer launches a resource -> CloudTrail logs it -> EventBridge matches the event pattern -> Lambda processes the event -> Slack alert delivered in under 60 seconds.

---

## Key Features

- **Real-time detection** of EC2 instance launches, RDS database creation, and Lambda function creation
- **Estimated costs** in both USD and INR (hourly and monthly projections)
- **Three-level severity classification**: LOW (< $0.10/hr), MEDIUM ($0.10-$1.00/hr), HIGH (> $1.00/hr)
- **One-click kill-switch** links directly to the AWS Console resource page for immediate termination
- **Slack Block Kit messages** with colour-coded severity and structured fields
- **Zero external dependencies** at runtime beyond `requests` (vendored in deployment zip)

---

## ROI Metrics

| Metric | Value |
|--------|-------|
| Detection time | < 60 seconds (vs 24-48 hours with AWS Cost Explorer) |
| Worst-case savings | Catching a `p4d.24xlarge` ($32.77/hr) in 60s vs 24h saves **$786** |
| Developer time saved | No manual console checks or billing dashboard monitoring |
| Deployment time | Under 15 minutes from scratch |
| Monthly Lambda cost | ~$0.00 (128MB, <30s invocations, only triggered on resource creation) |

---

## Prerequisites

- **AWS Account** with CloudTrail management event logging enabled (Write events)
- **Python 3.11+**
- **Slack incoming webhook URL** ([create one here](https://api.slack.com/messaging/webhooks))
- **AWS CLI** configured with admin permissions (for deployment)
- `pip` and `make` available in your terminal

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SLACK_WEBHOOK_URL` | Yes | -- | Slack incoming webhook HTTPS URL |
| `SNS_TOPIC_ARN` | No | -- | SNS topic ARN for email alerts (optional) |
| `INR_RATE` | No | `84` | USD to INR conversion rate |
| `WATCHED_REGION` | No | `ap-south-1` | AWS region to monitor |

---

## Quick Start (Local Development)

```bash
# Clone and navigate to project
cd cost-watchdog

# Install dependencies (runtime + test)
make install
# or: pip install -r requirements.txt

# Run the full test suite (no AWS credentials or network needed)
make test
# or: pytest tests/ -v
```

---

## Build & Deploy

### 1. Build the deployment package

```bash
make build
```

This creates `function.zip` containing the Lambda code with vendored `requests` library.

### 2. Deploy to AWS

```bash
bash infrastructure/setup.sh
```

The setup script creates all required AWS resources in dependency order:
1. SNS topic (optional, for email alerts)
2. IAM execution role with least-privilege permissions
3. Lambda function (`cost-watchdog`, Python 3.11, 128MB, 30s timeout)
4. EventBridge rule matching EC2/RDS/Lambda creation events
5. Lambda invoke permission for EventBridge

### 3. Verify deployment

After deployment, the EventBridge rule should show as **ENABLED**. You can test with:

```bash
aws lambda invoke \
  --function-name cost-watchdog \
  --payload fileb://tests/fixtures/ec2_run_instances.json \
  --region ap-south-1 \
  output.json && cat output.json
```

---

## Testing Locally with Mock Events

You can invoke the handler directly against fixture events without deploying:

```python
import json
import os

# Set required env var for local testing
os.environ["SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

from lambda.handler import lambda_handler

# Load a fixture event
with open("tests/fixtures/ec2_run_instances.json") as f:
    event = json.load(f)

# Invoke the handler
result = lambda_handler(event, None)
print(result)
# {"statusCode": 200, "body": "alert sent"}
```

Available fixtures:
- `tests/fixtures/ec2_run_instances.json` - EC2 RunInstances (t3.medium, 2 instances)
- `tests/fixtures/rds_create_db.json` - RDS CreateDBInstance (db.m5.large, MySQL)
- `tests/fixtures/lambda_create_function.json` - Lambda CreateFunction (256MB)

---

## Supported Resources

| Service | CloudTrail Event | Detected Action |
|---------|-----------------|-----------------|
| EC2 | `RunInstances` | Instance launch (supports multi-instance detection) |
| RDS | `CreateDBInstance` | Database creation |
| Lambda | `CreateFunction20150331` | Function creation |

---

## Severity Levels

| Level | Hourly Cost Range | Indicator | Slack Colour |
|-------|------------------|-----------|--------------|
| LOW | $0.00 - $0.099/hr | :green_circle: | `good` (green) |
| MEDIUM | $0.10 - $1.00/hr | :yellow_circle: | `warning` (yellow) |
| HIGH | > $1.00/hr | :red_circle: | `danger` (red) |

---

## Project Structure

```
cost-watchdog/
├── lambda/
│   ├── handler.py              # Lambda entry point (lambda_handler)
│   ├── resource_parser.py      # Per-service CloudTrail event parsers
│   ├── cost_calculator.py      # Pricing table + cost math + severity
│   ├── alert_builder.py        # Slack Block Kit message construction
│   ├── notifier.py             # HTTP POST to Slack webhook
│   └── vendor/                 # Vendored dependencies (created by `make build`)
├── infrastructure/
│   └── setup.sh                # AWS CLI deployment commands
├── tests/
│   ├── conftest.py             # Shared test fixtures and config
│   ├── fixtures/
│   │   ├── ec2_run_instances.json
│   │   ├── rds_create_db.json
│   │   └── lambda_create_function.json
│   ├── test_resource_parser.py
│   ├── test_cost_calculator.py
│   ├── test_alert_builder.py
│   ├── test_notifier.py
│   └── test_handler.py
├── requirements.txt            # Python dependencies
├── Makefile                    # build, test, deploy targets
├── pytest.ini                  # Test configuration
└── README.md                   # This file
```

---

## Pricing Coverage

The static pricing table includes on-demand prices for `ap-south-1`:

**EC2 (15 types):** t2.micro, t2.small, t2.medium, t3.micro, t3.small, t3.medium, t3.large, t3.xlarge, m5.large, m5.xlarge, c5.large, c5.xlarge, r5.large, p3.2xlarge, p4d.24xlarge

**RDS (6 classes):** db.t3.micro, db.t3.small, db.t3.medium, db.m5.large, db.m5.xlarge, db.r5.large

Unknown instance types fall back to safe defaults ($0.10/hr for EC2, $0.20/hr for RDS) ensuring alerts are always delivered.

---

## Makefile Targets

| Target | Description |
|--------|-------------|
| `make install` | Install all dependencies (runtime + test) |
| `make test` | Run the full pytest suite |
| `make build` | Create `function.zip` with vendored dependencies |
| `make clean` | Remove build artifacts |

---

## How It Works

1. **CloudTrail** captures all management write events in the monitored region
2. **EventBridge** matches events against the pattern (EC2/RDS/Lambda creation APIs)
3. **Lambda** is invoked with the raw CloudTrail event JSON:
   - **Resource Parser** extracts metadata (type, region, who launched it, instance details)
   - **Cost Calculator** looks up pricing, computes hourly/monthly costs, classifies severity
   - **Alert Builder** constructs a Slack Block Kit payload with all fields and a kill-switch URL
   - **Notifier** POSTs the payload to the configured Slack webhook
4. **Slack** displays a colour-coded, structured alert with a direct console link

Total latency: under 60 seconds from resource creation to Slack notification.

---

## Error Handling

- Missing CloudTrail fields are substituted with `"unknown"` (alerts still delivered)
- Unknown instance types use default pricing (never silently ignored)
- Invalid `INR_RATE` falls back to 84 with a logged warning
- Slack delivery failures raise exceptions, triggering EventBridge's built-in retry (up to 2 retries)
- Missing `SLACK_WEBHOOK_URL` returns a configuration error immediately

---

## License

Built for the AWS Kiro Hackathon.
