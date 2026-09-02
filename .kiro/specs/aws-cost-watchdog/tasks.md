# Implementation Plan: AWS Cost Watchdog

## Overview

Implement an event-driven serverless alerting system using Python 3.11 on AWS Lambda. The system detects cost-impacting resource launches (EC2, RDS, Lambda) via CloudTrail + EventBridge and delivers Slack notifications within 60 seconds. Implementation follows a bottom-up approach: core modules first, then handler orchestration, then tests and infrastructure.

## Tasks

- [x] 1. Set up project structure and configuration
  - [x] 1.1 Create directory structure and base files
    - Create `cost-watchdog/lambda/`, `cost-watchdog/tests/`, `cost-watchdog/tests/fixtures/`, `cost-watchdog/infrastructure/` directories
    - Create `cost-watchdog/requirements.txt` with `requests==2.31.0`, `pytest`, `pytest-mock`, `hypothesis` dependencies
    - Create `cost-watchdog/Makefile` with targets: `install`, `test`, `build` (zip packaging), `clean`
    - Create `cost-watchdog/tests/conftest.py` with shared test configuration
    - Create `pytest.ini` with testpaths, hypothesis max_examples=100 settings
    - _Requirements: 7.1, 7.4, 9.7_

- [x] 2. Implement pricing table and cost calculator
  - [x] 2.1 Create cost_calculator.py with static pricing tables
    - Create `cost-watchdog/lambda/cost_calculator.py`
    - Define `EC2_PRICES` dict with all 15 instance types from design (t2.micro through p4d.24xlarge) and their ap-south-1 hourly USD prices
    - Define `RDS_PRICES` dict with all 6 DB instance classes from design (db.t3.micro through db.r5.large)
    - Define constants: `DEFAULT_EC2_PRICE = 0.10`, `DEFAULT_RDS_PRICE = 0.20`, `DEFAULT_INR_RATE = 84`
    - _Requirements: 3.10, 3.11, 3.2, 3.4_

  - [x] 2.2 Implement cost calculation and severity functions
    - Implement `get_inr_rate()` that reads `INR_RATE` from environment, validates it is numeric and positive, falls back to 84 with logged warning on invalid values
    - Implement `get_severity(hourly_usd: float) -> str` with boundary logic: LOW (< $0.10), MEDIUM ($0.10-$1.00), HIGH (> $1.00)
    - Implement `calculate_cost(resource_type, instance_type, instance_count=1) -> dict` that looks up pricing, applies instance count multiplier for EC2, computes monthly as `hourly * 24 * 30`, converts to INR, rounds to spec precision (4 decimals hourly_usd, 2 decimals monthly/INR)
    - Handle unknown types with defaults and log warnings
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.12, 4.1, 4.2, 4.3, 4.5_

  - [ ]* 2.3 Write property tests for cost calculator
    - **Property 2: Monthly cost derivation** - verify `monthly == round(hourly * 720, 2)` for any non-negative hourly cost
    - **Property 3: INR conversion correctness** - verify `inr == round(usd * rate, 2)` for any positive rate
    - **Property 4: Severity boundary classification** - verify correct bucket for any non-negative hourly_usd
    - **Property 5: Instance count scaling** - verify `total == price * count` for counts 1-200
    - **Property 8: Monetary value rounding** - verify decimal place precision matches spec
    - **Property 9: Unknown type default pricing** - verify EC2 defaults to $0.10, RDS to $0.20 for unknown types
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3**

- [x] 3. Implement resource parser
  - [x] 3.1 Create resource_parser.py with per-service parsers
    - Create `cost-watchdog/lambda/resource_parser.py`
    - Implement `parse_ec2(detail: dict) -> dict` extracting instance_type, instance_count, region, launched_by (IAM ARN), resource_id
    - Implement `parse_rds(detail: dict) -> dict` extracting db_instance_class, engine, db_instance_identifier, region, launched_by
    - Implement `parse_lambda(detail: dict) -> dict` extracting function_name, memory_size, region, launched_by
    - Implement `parse_event(detail: dict, event_name: str) -> dict` dispatcher that routes to per-service parser based on event_name
    - Substitute `"unknown"` for any missing/absent required field without raising exceptions
    - Default instance_count to 1 if missing or < 1
    - Return structured dict with keys: resource_type, detail, region, launched_by, instance_type, instance_count, resource_id
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [ ]* 3.2 Write property test for missing field substitution
    - **Property 6: Missing field substitution** - verify that for any CloudTrail event dict with None or absent fields, Resource_Parser returns valid dict with "unknown" substitutions and no exceptions
    - **Validates: Requirements 2.4**

- [x] 4. Implement alert builder
  - [x] 4.1 Create alert_builder.py with Slack payload construction
    - Create `cost-watchdog/lambda/alert_builder.py`
    - Implement `build_kill_switch_url(resource_type, region, resource_id) -> str` using URL templates from design, URL-encoding special characters in resource_id, handling missing fields with empty strings and warning text
    - Implement `build_slack_payload(resource_info: dict, cost_info: dict) -> dict` constructing Block Kit attachment with: header, section fields (resource type, detail, region, launched_by, hourly cost USD+INR, monthly cost USD+INR, severity with emoji indicator), actions block with kill-switch button
    - Set attachment color: `"danger"` for HIGH, `"warning"` for MEDIUM, `"good"` for LOW
    - Render severity indicators: LOW=🟢, MEDIUM=🟡, HIGH=🔴
    - Ensure Kill_Switch_URL is no longer than 2048 characters
    - _Requirements: 4.4, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.2, 6.3_

  - [ ]* 4.2 Write property tests for alert builder
    - **Property 7: Kill-switch URL validity** - verify URL is <= 2048 chars and contains only valid URL characters for any resource type, region, and resource_id
    - **Property 10: Slack payload completeness** - verify all required fields present in output for any valid resource_info and cost_info dicts
    - **Validates: Requirements 5.6, 6.2**

- [x] 5. Implement notifier
  - [x] 5.1 Create notifier.py with Slack webhook delivery
    - Create `cost-watchdog/lambda/notifier.py`
    - Implement `send_slack_alert(payload: dict) -> None`
    - Validate `SLACK_WEBHOOK_URL` env var exists, is non-empty, and is a valid HTTPS URL; raise exception with logged error if invalid
    - POST JSON payload to webhook URL with 5-second timeout
    - Raise exception on non-200 HTTP status, network errors (connection refused, DNS failure), or timeout
    - Log error details on all failure paths
    - _Requirements: 6.1, 6.4, 6.5, 6.6, 6.7_

- [x] 6. Implement Lambda handler
  - [x] 6.1 Create handler.py orchestrating all modules
    - Create `cost-watchdog/lambda/handler.py`
    - Add `sys.path` insertion for vendored dependencies at module top
    - Implement `lambda_handler(event: dict, context: Any) -> dict`
    - Log full raw event payload on invocation (Requirement 7.6)
    - Validate `SLACK_WEBHOOK_URL` env var; return `{"statusCode": 500, "body": "configuration error"}` if missing
    - Extract event_name from event; return `{"statusCode": 200, "body": "ignored"}` for unsupported event names
    - Call Resource_Parser → Cost_Calculator → Alert_Builder → Notifier in sequence
    - Return `{"statusCode": 200, "body": "alert sent"}` on success
    - Catch all exceptions, log traceback, return `{"statusCode": 500, "body": "processing error"}`
    - _Requirements: 7.2, 7.3, 7.5, 7.6, 7.7, 7.8, 7.9_

- [x] 7. Checkpoint - Ensure all core modules compile and integrate
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Create test fixtures
  - [x] 8.1 Create mock CloudTrail event JSON fixtures
    - Create `cost-watchdog/tests/fixtures/ec2_run_instances.json` - RunInstances event with t3.medium, count 2, ap-south-1, valid IAM ARN
    - Create `cost-watchdog/tests/fixtures/rds_create_db.json` - CreateDBInstance with db.m5.large, mysql engine, valid identifier
    - Create `cost-watchdog/tests/fixtures/lambda_create_function.json` - CreateFunction20150331 with 256MB memory, function name
    - Each fixture must contain minimum fields required by Resource_Parser including requestParameters, userIdentity, and awsRegion
    - _Requirements: 9.1_

- [ ] 9. Implement unit tests
  - [ ]* 9.1 Write unit tests for resource_parser
    - Create `cost-watchdog/tests/test_resource_parser.py`
    - Test EC2 parsing: correct field extraction from fixture, instance count handling
    - Test RDS parsing: correct field extraction, engine and identifier
    - Test Lambda parsing: correct field extraction, memory size
    - Test missing fields: verify "unknown" substitution for each parser
    - Test unsupported event_name handling
    - _Requirements: 9.2_

  - [ ]* 9.2 Write unit tests for cost_calculator
    - Create `cost-watchdog/tests/test_cost_calculator.py`
    - Test severity boundary values: $0.099→LOW, $0.10→MEDIUM, $1.00→MEDIUM, $1.01→HIGH
    - Test known EC2 type pricing lookup (t3.large → $0.0864/hr)
    - Test unknown EC2 type default pricing ($0.10)
    - Test known RDS class pricing lookup (db.m5.large → $0.171/hr)
    - Test unknown RDS class default pricing ($0.20)
    - Test instance count multiplication for EC2
    - Test monthly cost calculation (hourly * 720)
    - Test INR conversion with default and custom rate
    - Test invalid INR_RATE env var fallback
    - _Requirements: 9.3_

  - [ ]* 9.3 Write unit tests for alert_builder
    - Create `cost-watchdog/tests/test_alert_builder.py`
    - Test kill-switch URL generation for EC2, RDS, Lambda with correct region/resource substitution
    - Test kill-switch URL with missing region/resource_id
    - Test Slack payload contains all required fields: resource_type, region, launched_by, hourly cost, monthly cost, severity indicator, kill-switch URL
    - Test colour mapping: HIGH→danger, MEDIUM→warning, LOW→good
    - Test severity emoji rendering: LOW→🟢, MEDIUM→🟡, HIGH→🔴
    - _Requirements: 9.5_

  - [ ]* 9.4 Write unit tests for notifier
    - Create `cost-watchdog/tests/test_notifier.py`
    - Mock Slack HTTP call; assert mock receives correct payload with resource type, severity, cost fields
    - Test missing SLACK_WEBHOOK_URL raises exception
    - Test invalid (non-HTTPS) SLACK_WEBHOOK_URL raises exception
    - Test non-200 response raises exception
    - Test timeout handling raises exception
    - _Requirements: 9.4_

  - [ ]* 9.5 Write integration test for handler
    - Create `cost-watchdog/tests/test_handler.py`
    - Test full pipeline with mocked Slack: EC2 event → alert sent → returns statusCode 200
    - Test missing SLACK_WEBHOOK_URL → returns statusCode 500 with "configuration error"
    - Test unsupported eventName → returns statusCode 200 with "ignored"
    - Test processing error (malformed event) → returns statusCode 500 with "processing error"
    - All tests run without AWS credentials or network access
    - _Requirements: 9.4, 9.7_

  - [ ]* 9.6 Write property test for round-trip consistency
    - **Property 1: Cost calculation round-trip consistency** - verify that formatting hourly_usd and monthly_usd to string and parsing back produces values within $0.001 tolerance
    - **Validates: Requirements 9.6**

- [x] 10. Checkpoint - Run full test suite
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Create infrastructure setup script
  - [x] 11.1 Create setup.sh with AWS CLI commands
    - Create `cost-watchdog/infrastructure/setup.sh`
    - Include commands in dependency order: create SNS topic, create IAM role (trust policy + permissions policy), create Lambda function (with zip deploy), create EventBridge rule (event pattern matching ec2/rds/lambda sources + specific eventNames), add Lambda permission for EventBridge, add EventBridge target
    - Include region variable defaulting to ap-south-1
    - Include comments indicating which resources to delete on failure for each step
    - Include optional SNS email subscription command
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

- [x] 12. Create README documentation
  - [x] 12.1 Create README.md with setup and usage instructions
    - Create `cost-watchdog/README.md`
    - Document: project overview, architecture diagram reference, prerequisites (AWS account, Slack webhook, Python 3.11)
    - Document: environment variables table (SLACK_WEBHOOK_URL, SNS_TOPIC_ARN, INR_RATE, WATCHED_REGION)
    - Document: local development setup (install deps, run tests)
    - Document: deployment steps (build zip, run setup.sh)
    - Document: testing locally with mock events
    - _Requirements: 8.4, 8.6_

- [x] 13. Final checkpoint - Verify complete implementation
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The design uses Python 3.11 — all implementation follows Python conventions
- Checkpoints ensure incremental validation at key integration points
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All tests run locally without AWS credentials or network access
- The `vendor/` directory for requests is created during the build step (Makefile `build` target), not committed to source

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "8.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1", "2.3"] },
    { "id": 4, "tasks": ["4.1", "3.2"] },
    { "id": 5, "tasks": ["5.1", "4.2"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["9.1", "9.2", "9.3", "9.4", "9.6"] },
    { "id": 8, "tasks": ["9.5"] },
    { "id": 9, "tasks": ["11.1", "12.1"] }
  ]
}
```
