# Requirements Document

## Introduction

AWS Cost Watchdog is an event-driven alerting tool that monitors an AWS account for cost-impacting resource launches (EC2 instances, RDS databases, Lambda functions, and similar services) and delivers a Slack notification within 60 seconds. Each alert includes the resource type, identity of who launched it, estimated hourly and monthly cost in USD and INR, a cost-severity rating, and a direct kill-switch link to terminate or stop the resource from the AWS Console.

The system is designed for AWS developers and platform engineers who want to eliminate surprise billing by catching runaway resources at the moment of creation rather than days later when the Cost Explorer report updates.

---

## Glossary

- **Watchdog**: The overall system composed of CloudTrail, EventBridge, the Lambda function, and the Slack notifier.
- **Event_Router**: The AWS EventBridge rule that receives CloudTrail management events and routes matching events to the Lambda function.
- **Cost_Calculator**: The module inside the Lambda function that computes hourly and monthly cost estimates from a static pricing table.
- **Alert_Builder**: The module inside the Lambda function that formats the Slack message payload.
- **Notifier**: The component responsible for delivering the formatted alert to the configured Slack webhook URL.
- **Resource_Parser**: The per-service module (EC2, RDS, Lambda) that extracts structured resource metadata from a raw CloudTrail event detail object.
- **Pricing_Table**: The in-memory static lookup table mapping AWS instance/class types to their on-demand USD/hour prices for the `ap-south-1` region.
- **Kill_Switch_URL**: A pre-formatted AWS Console deep-link URL included in each alert that navigates directly to the resource for termination or deletion.
- **Severity**: A three-level cost classification — LOW (< $0.10/hr), MEDIUM ($0.10–$1.00/hr), HIGH (> $1.00/hr).
- **INR_Rate**: The USD-to-INR conversion rate used for dual-currency display, set to 84 by default and configurable via environment variable.

---

## Requirements

### Requirement 1: Event Detection

**User Story:** As an AWS developer, I want the Watchdog to detect every EC2 instance launch, RDS database creation, and Lambda function creation in real time, so that I am alerted before significant cost accumulates.

#### Acceptance Criteria

1. WHEN a `RunInstances` CloudTrail management event is received by the Event_Router, THE Event_Router SHALL forward the full CloudTrail event JSON as the invocation payload to the Lambda function within 10 seconds of the event being recorded by CloudTrail.
2. WHEN a `CreateDBInstance` CloudTrail management event is received by the Event_Router, THE Event_Router SHALL forward the full CloudTrail event JSON as the invocation payload to the Lambda function within 10 seconds of the event being recorded by CloudTrail.
3. WHEN a `CreateFunction20150331` CloudTrail management event is received by the Event_Router, THE Event_Router SHALL forward the full CloudTrail event JSON as the invocation payload to the Lambda function within 10 seconds of the event being recorded by CloudTrail.
4. WHEN a CloudTrail management event with an `eventName` that is not one of `RunInstances`, `CreateDBInstance`, or `CreateFunction20150331` is received, THE Event_Router SHALL discard the event without invoking the Lambda function.
5. THE Event_Router SHALL monitor only the `ap-south-1` AWS region by default; IF the `WATCHED_REGION` environment variable is set to a non-empty value, THEN the Event_Router SHALL monitor only the region specified by that variable instead.
6. IF the Event_Router forwards an event to the Lambda function and the Lambda invocation fails, THEN the Event_Router SHALL retry the invocation up to 2 times with exponential backoff before discarding the event.

---

### Requirement 2: Resource Parsing

**User Story:** As an AWS developer, I want each alert to contain accurate resource metadata, so that I can immediately understand what was launched, by whom, and where.

#### Acceptance Criteria

1. WHEN a `RunInstances` event is parsed, THE Resource_Parser SHALL extract instance type, requested instance count (from `requestParameters`), AWS region, and the IAM ARN of the user who launched the instance.
2. WHEN a `CreateDBInstance` event is parsed, THE Resource_Parser SHALL extract DB instance class, database engine, DB instance identifier, AWS region, and the IAM ARN of the user who created the database.
3. WHEN a `CreateFunction20150331` event is parsed, THE Resource_Parser SHALL extract function name, memory size in MB, AWS region, and the IAM ARN of the user who created the function.
4. IF a required field is absent from the CloudTrail event detail, THEN THE Resource_Parser SHALL substitute the string `"unknown"` for that field and continue processing without raising an exception.
5. THE Resource_Parser SHALL return a structured dictionary containing the keys: `resource_type`, `detail`, `region`, `launched_by`, `hourly_usd`, `monthly_usd`, and `monthly_inr`, where `resource_type` is one of `"EC2"`, `"RDS"`, or `"Lambda"` corresponding to the parsed event type.
6. THE Resource_Parser SHALL represent all monetary values (`hourly_usd`, `monthly_usd`, `monthly_inr`) as numeric values rounded to exactly 2 decimal places.
7. IF the parsed event type does not have a matching cost entry in the Pricing_Table, THEN THE Resource_Parser SHALL set `hourly_usd`, `monthly_usd`, and `monthly_inr` to `0.00`.

---

### Requirement 3: Cost Estimation

**User Story:** As an AWS developer, I want the alert to show me estimated hourly and monthly cost, so that I can immediately assess the financial impact of the resource.

#### Acceptance Criteria

1. WHEN cost estimation is requested for a known EC2 instance type, THE Cost_Calculator SHALL return the hourly USD price from the Pricing_Table for the `ap-south-1` region, rounded to four decimal places.
2. WHEN cost estimation is requested for an unknown EC2 instance type, THE Cost_Calculator SHALL return a default hourly price of `$0.10` and log a warning containing the unrecognised instance type string.
3. WHEN cost estimation is requested for a known RDS instance class, THE Cost_Calculator SHALL return the hourly USD price from the Pricing_Table for the `ap-south-1` region, rounded to four decimal places.
4. WHEN cost estimation is requested for an unknown RDS instance class, THE Cost_Calculator SHALL return a default hourly price of `$0.20` and log a warning containing the unrecognised instance class string.
5. WHEN multiple EC2 instances are launched in a single `RunInstances` event, THE Cost_Calculator SHALL multiply the per-instance hourly price by the instance count (range: 1 to 200) to produce the total hourly cost.
6. THE Cost_Calculator SHALL compute monthly cost as `hourly_cost × 24 × 30`, rounded to two decimal places.
7. THE Cost_Calculator SHALL compute the INR equivalent using the formula `usd × INR_RATE`, rounded to two decimal places, where `INR_RATE` defaults to `84` and is overridable via the `INR_RATE` environment variable.
8. IF the `INR_RATE` environment variable is set to a non-numeric or non-positive value, THEN THE Cost_Calculator SHALL use the default `INR_RATE` of `84` and log a warning indicating the invalid override value.
9. THE Cost_Calculator SHALL return cost estimation results containing: hourly cost in USD, monthly cost in USD, hourly cost in INR, and monthly cost in INR.
10. THE Pricing_Table SHALL include on-demand prices for at minimum the following EC2 types in `ap-south-1`: `t2.micro`, `t2.small`, `t2.medium`, `t3.micro`, `t3.small`, `t3.medium`, `t3.large`, `t3.xlarge`, `m5.large`, `m5.xlarge`, `c5.large`, `c5.xlarge`, `r5.large`, `p3.2xlarge`, `p4d.24xlarge`.
11. THE Pricing_Table SHALL include on-demand prices for at minimum the following RDS instance classes in `ap-south-1`: `db.t3.micro`, `db.t3.small`, `db.t3.medium`, `db.m5.large`, `db.m5.xlarge`, `db.r5.large`.
12. IF the instance count in a `RunInstances` event is missing or less than 1, THEN THE Cost_Calculator SHALL default the instance count to 1.

---

### Requirement 4: Severity Classification

**User Story:** As an AWS developer, I want each alert to carry a severity label, so that I can triage and prioritise termination of the most expensive resources first.

#### Acceptance Criteria

1. WHEN the computed `hourly_usd` value is greater than or equal to `0` and less than `0.10`, THE Cost_Calculator SHALL assign the Severity level `LOW`.
2. WHEN the computed `hourly_usd` value is greater than or equal to `0.10` and less than or equal to `1.00`, THE Cost_Calculator SHALL assign the Severity level `MEDIUM`.
3. WHEN the computed `hourly_usd` value is greater than `1.00`, THE Cost_Calculator SHALL assign the Severity level `HIGH`.
4. THE Alert_Builder SHALL render `LOW` severity with a green indicator (🟢), `MEDIUM` with a yellow indicator (🟡), and `HIGH` with a red indicator (🔴) in the Slack message.
5. IF the `hourly_usd` value cannot be computed (e.g., the Pricing_Table lookup fails and no default applies), THEN THE Cost_Calculator SHALL assign the Severity level `MEDIUM` and log a warning explaining the fallback.

---

### Requirement 5: Kill-Switch URL Generation

**User Story:** As an AWS developer, I want each alert to include a direct link to the relevant AWS Console page, so that I can terminate the resource in one click without searching the console.

#### Acceptance Criteria

1. WHEN an EC2 `RunInstances` alert is built, THE Alert_Builder SHALL include a Kill_Switch_URL pointing to `https://console.aws.amazon.com/ec2/v2/home?region={region}#Instances`.
2. WHEN an RDS `CreateDBInstance` alert is built, THE Alert_Builder SHALL include a Kill_Switch_URL pointing to `https://console.aws.amazon.com/rds/home?region={region}#database:id={db_instance_identifier}`.
3. WHEN a Lambda `CreateFunction` alert is built, THE Alert_Builder SHALL include a Kill_Switch_URL pointing to `https://console.aws.amazon.com/lambda/home?region={region}#/functions/{function_name}`.
4. WHEN constructing a Kill_Switch_URL, THE Alert_Builder SHALL substitute the actual AWS region and resource identifier values extracted from the CloudTrail event into the URL template, URL-encoding any special characters in the resource identifier.
5. IF the region or resource identifier required for a Kill_Switch_URL is missing or empty in the CloudTrail event, THEN THE Alert_Builder SHALL include the Kill_Switch_URL with the available fields substituted and leave missing placeholders as empty strings, and append a warning in the alert message indicating which field was unavailable.
6. WHEN an alert is built for a supported event type, THE Alert_Builder SHALL produce a Kill_Switch_URL that is no longer than 2048 characters and contains only valid URL characters after encoding.

---

### Requirement 6: Slack Alert Delivery

**User Story:** As an AWS developer, I want to receive a Slack message within 60 seconds of a resource being launched, so that I can act before meaningful cost accumulates.

#### Acceptance Criteria

1. WHEN a parsed and priced resource event is ready, THE Notifier SHALL deliver a Slack message to the webhook URL configured in the `SLACK_WEBHOOK_URL` environment variable within 30 seconds of the Lambda function being invoked.
2. THE Notifier SHALL format the Slack message using Block Kit attachments, including fields for: resource type, resource detail, region, launched-by IAM ARN, hourly cost (USD and INR), monthly cost (USD and INR), Severity level, and Kill_Switch_URL.
3. THE Notifier SHALL set the Slack attachment colour to `"danger"` for HIGH severity, `"warning"` for MEDIUM severity, and `"good"` for LOW severity.
4. IF the Slack webhook call returns an HTTP status code other than `200`, or if a network error occurs (connection refused, DNS failure, or timeout exceeded), THEN THE Notifier SHALL log the error details and raise an exception so the Lambda invocation is marked as failed.
5. IF the `SLACK_WEBHOOK_URL` environment variable is not set or is empty, THEN THE Notifier SHALL log an error message and raise an exception so the Lambda invocation is marked as failed.
6. THE Notifier SHALL set a per-request HTTP timeout of 5 seconds on the Slack webhook call; IF this timeout is exceeded, THEN the call SHALL be treated as a failed delivery attempt.
7. IF the `SLACK_WEBHOOK_URL` value is not a valid HTTPS URL, THEN THE Notifier SHALL log a validation error and raise an exception without attempting delivery.
8. THE Watchdog SHALL deliver the Slack alert within 60 seconds of the CloudTrail event being generated, measured from event timestamp to Slack message receipt.

---

### Requirement 7: Lambda Function Configuration

**User Story:** As a platform engineer, I want the Lambda function to be self-contained and configurable via environment variables, so that I can deploy it to any AWS account without modifying source code.

#### Acceptance Criteria

1. THE Watchdog SHALL package all runtime dependencies (including `requests`) inside the Lambda deployment zip artifact so that no external layers are required.
2. THE Watchdog SHALL read `SNS_TOPIC_ARN`, `SLACK_WEBHOOK_URL`, `INR_RATE`, and `WATCHED_REGION` exclusively from Lambda environment variables, with no hardcoded values in source code.
3. IF any of the required environment variables (`SLACK_WEBHOOK_URL`) is missing or empty at invocation time, THEN THE Watchdog SHALL log an error message indicating which variable is missing and return `{"statusCode": 500, "body": "configuration error"}` without sending any alert.
4. THE Watchdog SHALL execute within the AWS Lambda `python3.11` runtime with a memory allocation of 128 MB.
5. THE Watchdog SHALL complete its execution, including Slack delivery, within a 30-second Lambda timeout.
6. WHEN the Lambda function is invoked, THE Watchdog SHALL log the full raw EventBridge event payload to CloudWatch Logs before any processing begins.
7. WHEN processing completes successfully, THE Watchdog SHALL return `{"statusCode": 200, "body": "alert sent"}`.
8. IF processing fails due to an unreachable external service or unexpected error, THEN THE Watchdog SHALL log the error details to CloudWatch Logs and return `{"statusCode": 500, "body": "processing error"}`.
9. WHEN the Lambda function receives an event for an unsupported `eventName`, THE Watchdog SHALL return `{"statusCode": 200, "body": "ignored"}` without sending any alert.

---

### Requirement 8: Infrastructure Setup

**User Story:** As a platform engineer, I want all required AWS resources to be creatable via documented CLI commands, so that the system can be deployed in under 15 minutes on any AWS account.

#### Acceptance Criteria

1. THE Watchdog SHALL require a CloudTrail trail with management event logging enabled for Write operations in the same region where the Lambda function is deployed.
2. THE Watchdog SHALL require an IAM execution role for the Lambda function that grants only `sns:Publish`, `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions, with no wildcard resource ARNs and no additional action permissions.
3. THE Watchdog SHALL require an EventBridge rule whose event pattern matches CloudTrail events with `source` values `["aws.ec2", "aws.rds", "aws.lambda"]` and `eventName` values `["RunInstances", "CreateDBInstance", "CreateFunction20150331"]`.
4. THE Watchdog setup documentation SHALL include CLI commands for each of the following steps in dependency order: creating the SNS topic, creating the IAM role, creating the Lambda function, creating the EventBridge rule, and granting EventBridge permission to invoke the Lambda function.
5. WHERE SNS email alerting is also desired, THE Watchdog SHALL support subscribing an email address to the SNS topic so that alert notifications are delivered to both Slack and the subscribed email address.
6. WHEN a platform engineer executes all documented CLI commands sequentially on a new AWS account with appropriate admin permissions, THE Watchdog SHALL be fully operational within 15 minutes, verified by the EventBridge rule showing as ENABLED and the Lambda function responding to a test invocation.
7. IF any CLI command in the setup sequence fails, THEN THE Watchdog setup documentation SHALL indicate which preceding resources must be deleted before retrying, so that no orphaned resources remain.

---

### Requirement 9: Local Testability

**User Story:** As a developer, I want to run the Lambda handler locally against mock events before deploying, so that I can verify cost calculations and alert formatting without incurring AWS charges.

#### Acceptance Criteria

1. THE Watchdog test suite SHALL include at least one mock EventBridge event fixture for each supported resource type: EC2, RDS, and Lambda, where each fixture contains the minimum fields required by the Resource_Parser.
2. WHEN the test suite is executed locally, THE Watchdog test suite SHALL assert that the `Resource_Parser` returns `resource_type`, `hourly_usd`, and `monthly_usd` values matching the expected outputs defined in each fixture's corresponding assertion data.
3. WHEN the test suite is executed locally, THE Watchdog test suite SHALL assert that the `Cost_Calculator` correctly classifies Severity level boundaries using at minimum these four test values: `$0.099` (expected: LOW), `$0.10` (expected: MEDIUM), `$1.00` (expected: MEDIUM), and `$1.01` (expected: HIGH).
4. THE Watchdog test suite SHALL mock the Slack HTTP call so that local tests do not require network access or a real webhook URL, and SHALL assert that the mock receives a payload containing the resource type, severity level, and cost fields.
5. THE Watchdog test suite SHALL include at least one test that invokes the `Alert_Builder` with a known resource metadata dictionary and asserts the formatted Slack message contains the resource type, region, launched-by ARN, hourly cost, monthly cost, Severity indicator, and Kill_Switch_URL.
6. FOR ALL valid resource metadata dictionaries containing non-negative `hourly_usd` and `monthly_usd` values, THE Watchdog test suite SHALL verify that parsing then formatting then parsing these fields produces values equal to the originals within a tolerance of `$0.001`.
7. THE Watchdog test suite SHALL execute all tests to completion without requiring AWS credentials, network access, or environment variables beyond those explicitly set within the test configuration.
