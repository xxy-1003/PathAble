# PathAble AWS Slow-Loop Cost and Deployment Plan

**Prepared for**: PathAble Team / OpenCV AI Competition 2026  
**Scope**: AWS Slow Loop, Graviton Re-Check with COOL, DynamoDB Map Sync, Bedrock Tie-Breaker, and Facilities Human Review  
**Date**: 24 October 2026  
**Status**: Ready for Team Lead / Mentor Approval prior to provisioning

---

## 1. Executive Summary & Cost Safeguards

PathAble separates safety from the cloud:
- **Fast Loop (Device)**: All immediate collision avoidance, Dijkstra rerouting, and STOP decisions run 100% offline on the laptop within 700 ms. Safety never waits on the network or AWS.
- **Slow Loop (AWS)**: Asynchronous re-checks, MS 1184 corridor clearance verification, Bedrock tie-breaking, facilities human review, and shared map version synchronization.

**Cost Guarantee**: Total estimated cloud expenditure for full development, Graviton benchmarking, and demonstration is **under $5.00 USD**.

---

## 2. Itemized Cost Estimate

| AWS Service | Usage Profile during Testing & Demo | Pricing Rate (us-east-1 / ap-southeast-1) | Estimated Cost |
| :--- | :--- | :--- | :--- |
| **EC2 `c7g.large` (Graviton3)** | 20 hours total (benchmarking + live demo, stopped when idle) | \$0.0725 / hour (On-Demand) | **\$1.45** |
| **AWS Lambda (ARM64)** | ~5,000 invocations (intake, validation, map sync) | Free Tier (1M req/mo included) | **\$0.00** |
| **Amazon DynamoDB** | Pay-Per-Request (Events, Shared Map, Tickets) | 25 RCU/WCU Free Tier (< 5 MB data) | **\$0.00** |
| **Amazon S3** | Keyframes with 7-day auto lifecycle expiry (< 1 GB) | \$0.023 / GB-month | **\$0.02** |
| **Amazon Bedrock (Nova Lite)** | ~30 tie-breaker calls for tool conflicts | \$0.00006 / 1k input, \$0.00024 / 1k output | **\$0.05** |
| **Amazon SNS** | Facilities approval email dispatch | Free Tier (1,000 emails/month) | **\$0.00** |
| **CloudWatch Logs** | Audit decision trace logging (< 500 MB) | Free Tier (5 GB log ingestion) | **\$0.00** |
| **Buffer / Contingency** | Network transfer and edge cases | — | **\$1.50** |
| **TOTAL ESTIMATED COST** | — | — | **~\$3.02 USD** |

---

## 3. Strict Budget Controls & Spending Caps

To guarantee zero surprise billing:
1. **AWS Budgets Alert**:
   - A hard budget alert will be provisioned at **$10.00 USD**.
   - Notifications dispatched via SNS to the team lead immediately if forecasted spend reaches 80% ($8.00).
2. **EC2 Auto-Stop Safeguard**:
   - CloudWatch Alarm monitoring EC2 CPU utilization; if CPU < 2% for 15 minutes, instance automatically stops.
3. **S3 Privacy & Retention**:
   - 7-day automatic lifecycle expiration configured on `KeyframesBucket`. No images persist indefinitely.
   - `BlockPublicAcls: true`, `BlockPublicPolicy: true`, `IgnorePublicAcls: true`, `RestrictPublicBuckets: true`.

---

## 4. Required AWS Permissions & Access Prereqs

Before running live provisioning against AWS, the following access must be configured:
1. **IAM Credentials**: An AWS access key or IAM role with permissions:
   - `apigateway:*` (HTTP API creation)
   - `lambda:*` (Serverless functions)
   - `dynamodb:*` (Events, Shared Map, Tickets tables)
   - `s3:*` (Keyframes bucket with lifecycle rule)
   - `sns:*` (Approval notifications topic)
   - `bedrock:InvokeModel` (Model: `amazon.nova-lite-v1:0` enabled in target region)
   - `ec2:RunInstances`, `ec2:DescribeInstances`, `ec2:StopInstances` (Instance type: `c7g.large`)
2. **Region & Graviton Quota**:
   - Recommended region: `us-east-1` or `ap-southeast-1`.
   - Graviton quota: vCPU quota for `c7g` family must be >= 2 vCPUs.
3. **Bedrock Model Access**:
   - Amazon Nova Lite model access toggled to "Granted" in the AWS Bedrock console.

---

## 5. Deployment Procedure (Upon Approval)

1. **Deploy Serverless Slow Loop**:
   ```bash
   sam build -t production/v3/cloud/infra/template.yaml
   sam deploy --guided --stack-name pathable-slow-loop
   ```
2. **Seed Initial 6-Node Prototype Map**:
   ```bash
   curl -X POST https://<api-id>.execute-api.<region>.amazonaws.com/api/v1/map \
        -H "Content-Type: application/json" \
        -d @production/map_graph.json
   ```
3. **Run Live Verification**:
   ```bash
   python -m unittest production.v3.cloud.tests.test_api_and_review
   ```
