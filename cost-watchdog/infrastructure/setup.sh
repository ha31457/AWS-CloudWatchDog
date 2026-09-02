#!/bin/bash
# =============================================================================
# AWS Cost Watchdog - Infrastructure Setup Script
# =============================================================================
# This script deploys the entire Cost Watchdog stack using AWS CLI commands.
# Prerequisites:
#   - AWS CLI v2 configured with admin permissions
#   - Slack incoming webhook URL
#   - Lambda deployment zip built via `make build` in the project root
#   - CloudTrail trail enabled for management write events in the target region
#
# Usage:
#   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
#   bash infrastructure/setup.sh
# =============================================================================

set -e

# -----------------------------------------------------------------------------
# Configuration Variables
# -----------------------------------------------------------------------------
REGION="${WATCHED_REGION:-ap-south-1}"
FUNCTION_NAME="cost-watchdog"
ROLE_NAME="cost-watchdog-lambda-role"
RULE_NAME="cost-watchdog-event-rule"
SNS_TOPIC_NAME="cost-watchdog-alerts"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
INR_RATE="${INR_RATE:-84}"

echo "============================================="
echo "AWS Cost Watchdog - Infrastructure Deployment"
echo "============================================="
echo "Region:      ${REGION}"
echo "Account ID:  ${ACCOUNT_ID}"
echo "Function:    ${FUNCTION_NAME}"
echo "Role:        ${ROLE_NAME}"
echo "Rule:        ${RULE_NAME}"
echo "SNS Topic:   ${SNS_TOPIC_NAME}"
echo "============================================="
echo ""

# Validate required environment variables
if [ -z "${SLACK_WEBHOOK_URL}" ]; then
    echo "ERROR: SLACK_WEBHOOK_URL environment variable is required."
    echo "Export it before running this script:"
    echo "  export SLACK_WEBHOOK_URL=\"https://hooks.slack.com/services/...\""
    exit 1
fi

# -----------------------------------------------------------------------------
# Step 1: Create SNS Topic
# -----------------------------------------------------------------------------
# Creates an SNS topic for optional email alert delivery alongside Slack.
# On failure cleanup: aws sns delete-topic --topic-arn <TOPIC_ARN> --region ${REGION}
echo "[Step 1/7] Creating SNS topic: ${SNS_TOPIC_NAME}..."

SNS_TOPIC_ARN=$(aws sns create-topic \
    --name "${SNS_TOPIC_NAME}" \
    --region "${REGION}" \
    --query 'TopicArn' \
    --output text)

echo "  SNS Topic ARN: ${SNS_TOPIC_ARN}"
echo "  Done."
echo ""

# -----------------------------------------------------------------------------
# Step 2: Create IAM Execution Role
# -----------------------------------------------------------------------------
# Creates the Lambda execution role with least-privilege permissions.
# The role allows only CloudWatch Logs writes and SNS Publish.
# On failure cleanup:
#   aws iam delete-role-policy --role-name ${ROLE_NAME} --policy-name cost-watchdog-permissions
#   aws iam delete-role --role-name ${ROLE_NAME}
#   (Also delete SNS topic from Step 1)
echo "[Step 2/7] Creating IAM execution role: ${ROLE_NAME}..."

# Trust policy: allows Lambda service to assume this role
TRUST_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "lambda.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
EOF
)

aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "Execution role for Cost Watchdog Lambda function" \
    --query 'Role.Arn' \
    --output text

# Permissions policy: CloudWatch Logs + SNS Publish (no wildcard resource ARNs)
PERMISSIONS_POLICY=$(cat <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/lambda/${FUNCTION_NAME}:*"
        },
        {
            "Effect": "Allow",
            "Action": "sns:Publish",
            "Resource": "arn:aws:sns:${REGION}:${ACCOUNT_ID}:${SNS_TOPIC_NAME}"
        }
    ]
}
EOF
)

aws iam put-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-name "cost-watchdog-permissions" \
    --policy-document "${PERMISSIONS_POLICY}"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  Role ARN: ${ROLE_ARN}"
echo "  Done."
echo ""

# Wait for IAM role to propagate (IAM is eventually consistent)
echo "  Waiting 10 seconds for IAM role propagation..."
sleep 10

# -----------------------------------------------------------------------------
# Step 3: Create Lambda Function
# -----------------------------------------------------------------------------
# Deploys the Lambda function from the pre-built zip artifact.
# Assumes `make build` has been run and function.zip exists in the project root.
# On failure cleanup:
#   aws lambda delete-function --function-name ${FUNCTION_NAME} --region ${REGION}
#   (Also delete IAM role and SNS topic from Steps 1-2)
echo "[Step 3/7] Creating Lambda function: ${FUNCTION_NAME}..."

# Check that function.zip exists
if [ ! -f "function.zip" ]; then
    echo "ERROR: function.zip not found. Run 'make build' first."
    echo "Cleanup needed: delete IAM role and SNS topic created in Steps 1-2."
    exit 1
fi

aws lambda create-function \
    --function-name "${FUNCTION_NAME}" \
    --runtime python3.11 \
    --handler handler.lambda_handler \
    --zip-file fileb://function.zip \
    --memory-size 128 \
    --timeout 30 \
    --role "${ROLE_ARN}" \
    --environment "Variables={SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL},INR_RATE=${INR_RATE},WATCHED_REGION=${REGION},SNS_TOPIC_ARN=${SNS_TOPIC_ARN}}" \
    --region "${REGION}" \
    --query 'FunctionArn' \
    --output text

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"
echo "  Lambda ARN: ${LAMBDA_ARN}"
echo "  Done."
echo ""

# -----------------------------------------------------------------------------
# Step 4: Create EventBridge Rule
# -----------------------------------------------------------------------------
# Creates an EventBridge rule that matches CloudTrail management write events
# for EC2 RunInstances, RDS CreateDBInstance, and Lambda CreateFunction.
# On failure cleanup:
#   aws events remove-targets --rule ${RULE_NAME} --ids "cost-watchdog-target" --region ${REGION}
#   aws events delete-rule --name ${RULE_NAME} --region ${REGION}
#   (Also delete Lambda, IAM role, and SNS topic from Steps 1-3)
echo "[Step 4/7] Creating EventBridge rule: ${RULE_NAME}..."

EVENT_PATTERN=$(cat <<EOF
{
    "source": ["aws.ec2", "aws.rds", "aws.lambda"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
        "eventName": [
            "RunInstances",
            "CreateDBInstance",
            "CreateFunction20150331"
        ]
    }
}
EOF
)

RULE_ARN=$(aws events put-rule \
    --name "${RULE_NAME}" \
    --event-pattern "${EVENT_PATTERN}" \
    --state ENABLED \
    --description "Routes EC2/RDS/Lambda creation events to Cost Watchdog" \
    --region "${REGION}" \
    --query 'RuleArn' \
    --output text)

echo "  Rule ARN: ${RULE_ARN}"
echo "  Done."
echo ""

# -----------------------------------------------------------------------------
# Step 5: Add Lambda Permission for EventBridge
# -----------------------------------------------------------------------------
# Grants EventBridge permission to invoke the Lambda function.
# On failure cleanup:
#   aws lambda remove-permission --function-name ${FUNCTION_NAME} --statement-id "EventBridgeInvoke" --region ${REGION}
#   (Also delete EventBridge rule, Lambda, IAM role, and SNS topic from Steps 1-4)
echo "[Step 5/7] Adding Lambda invoke permission for EventBridge..."

aws lambda add-permission \
    --function-name "${FUNCTION_NAME}" \
    --statement-id "EventBridgeInvoke" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "${RULE_ARN}" \
    --region "${REGION}" \
    --output text

echo "  Done."
echo ""

# -----------------------------------------------------------------------------
# Step 6: Add EventBridge Target (Lambda Function)
# -----------------------------------------------------------------------------
# Connects the EventBridge rule to the Lambda function as its target.
# On failure cleanup:
#   aws events remove-targets --rule ${RULE_NAME} --ids "cost-watchdog-target" --region ${REGION}
#   (Also delete Lambda permission, EventBridge rule, Lambda, IAM role, SNS topic from Steps 1-5)
echo "[Step 6/7] Adding Lambda as EventBridge rule target..."

aws events put-targets \
    --rule "${RULE_NAME}" \
    --targets "Id=cost-watchdog-target,Arn=${LAMBDA_ARN}" \
    --region "${REGION}" \
    --output text

echo "  Done."
echo ""

# -----------------------------------------------------------------------------
# Step 7 (Optional): Subscribe Email to SNS Topic
# -----------------------------------------------------------------------------
# Uncomment and set EMAIL_ADDRESS to receive alert emails alongside Slack.
# On failure cleanup:
#   aws sns unsubscribe --subscription-arn <SUBSCRIPTION_ARN> --region ${REGION}

echo "[Step 7/7] SNS Email Subscription (optional)..."

if [ -n "${ALERT_EMAIL}" ]; then
    echo "  Subscribing ${ALERT_EMAIL} to SNS topic..."
    aws sns subscribe \
        --topic-arn "${SNS_TOPIC_ARN}" \
        --protocol email \
        --notification-endpoint "${ALERT_EMAIL}" \
        --region "${REGION}" \
        --output text
    echo "  Subscription pending confirmation. Check your email to confirm."
else
    echo "  Skipped. Set ALERT_EMAIL env var to subscribe an email address."
    echo "  Example: export ALERT_EMAIL=\"alerts@example.com\""
fi

echo ""
echo "============================================="
echo "Deployment Complete!"
echo "============================================="
echo ""
echo "Resources created:"
echo "  - SNS Topic:        ${SNS_TOPIC_ARN}"
echo "  - IAM Role:         ${ROLE_ARN}"
echo "  - Lambda Function:  ${LAMBDA_ARN}"
echo "  - EventBridge Rule: ${RULE_ARN}"
echo ""
echo "To verify, check the EventBridge rule status:"
echo "  aws events describe-rule --name ${RULE_NAME} --region ${REGION}"
echo ""
echo "To test with a sample invocation:"
echo "  aws lambda invoke --function-name ${FUNCTION_NAME} --payload fileb://tests/fixtures/ec2_run_instances.json --region ${REGION} output.json"
echo ""
echo "============================================="
echo "Cleanup Commands (if needed):"
echo "============================================="
echo "  aws events remove-targets --rule ${RULE_NAME} --ids \"cost-watchdog-target\" --region ${REGION}"
echo "  aws lambda remove-permission --function-name ${FUNCTION_NAME} --statement-id \"EventBridgeInvoke\" --region ${REGION}"
echo "  aws events delete-rule --name ${RULE_NAME} --region ${REGION}"
echo "  aws lambda delete-function --function-name ${FUNCTION_NAME} --region ${REGION}"
echo "  aws iam delete-role-policy --role-name ${ROLE_NAME} --policy-name cost-watchdog-permissions"
echo "  aws iam delete-role --role-name ${ROLE_NAME}"
echo "  aws sns delete-topic --topic-arn ${SNS_TOPIC_ARN}"
echo "============================================="
