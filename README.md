
---

# API Health Monitoring System

---

## 1. Overview

This project implements a **self-hosted API health monitoring system** that periodically checks the health of user-defined API endpoints and notifies users when **meaningful health state changes** occur.

The system is designed with a strong focus on:

* scalability
* reliability
* operational correctness
* infrastructure-as-code (Terraform)

No third-party or managed monitoring tools are used.

---

## 2. Key Features

* Configurable API endpoints (URL, interval, timeout, expected status)
* Real HTTP-based health checks
* Failure and recovery thresholds to avoid alert spam
* State-change–based notifications (no repeated alerts)
* Scalable scheduling using DynamoDB GSI
* Horizontal scaling via bucket partitioning
* AWS-native deployment using Terraform

---

## 3. High-Level Architecture

```mermaid
flowchart LR
  U["User or Admin"] -->|"Create endpoint configs"| DDB[("DynamoDB<br/>endpoints and state")]

  EB["EventBridge<br/>schedule"] -->|"Run task"| ECS["ECS Fargate task<br/>Python worker"]

  ECS -->|"Query due endpoints (GSI)"| DDB
  ECS -->|"HTTP requests"| API["External API<br/>endpoints"]
  ECS -->|"Update state and next_check_at"| DDB
  ECS -->|"Publish alert on state change"| SNS["SNS topic<br/>Email alerts"]
  ECS -->|"Write logs"| CW["CloudWatch Logs"]

  classDef aws fill:#fff3e0,stroke:#ef6c00,stroke-width:1px;
  classDef data fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px;
  classDef external fill:#e3f2fd,stroke:#1565c0,stroke-width:1px;
  classDef logs fill:#f3e5f5,stroke:#6a1b9a,stroke-width:1px;

  class EB,ECS,SNS aws;
  class DDB data;
  class API external;
  class CW logs;
```

**Description**
A scheduled EventBridge rule triggers a containerized worker running on ECS Fargate.
The worker queries DynamoDB for due endpoints, performs health checks, persists state, and sends alerts via SNS.

---

## 4. Health Check & Alerting Flow

```mermaid
sequenceDiagram
  autonumber
  participant EB as EventBridge
  participant ECS as ECS Worker
  participant DDB as DynamoDB
  participant API as API Endpoint
  participant SNS as SNS Email

  EB->>ECS: Trigger scheduled run
  ECS->>DDB: Query due endpoints using GSI

  loop For each due endpoint
    ECS->>API: Send HTTP request with timeout
    alt Check success and rules pass
      API-->>ECS: Response
      ECS->>ECS: Increase success counter
    else Check fails
      API-->>ECS: Timeout or network error or bad status
      ECS->>ECS: Increase failure counter
    end

    ECS->>ECS: Compute new state using thresholds
    ECS->>DDB: Store state and next_check_at

    alt State changed
      ECS->>SNS: Send notification
    else No state change
      ECS-->>ECS: No alert
    end
  end
```

**Key Principle**
Alerts are emitted **only when the state changes**:

* HEALTHY → UNHEALTHY
* UNHEALTHY → HEALTHY

This prevents repeated notifications during continuous failures.

---

## 5. DynamoDB Data Model

### Primary Table: `endpoints`

| Attribute       | Purpose                  |
| --------------- | ------------------------ |
| endpoint_id     | Primary key              |
| url             | API endpoint             |
| interval_sec    | Check frequency          |
| state           | HEALTHY / UNHEALTHY      |
| consec_fail     | Consecutive failures     |
| consec_succ     | Consecutive successes    |
| schedule_bucket | Partition bucket         |
| next_check_at   | Next eligible check time |
| enabled         | Soft disable flag        |

---

## 6. Scalable Scheduling Design

```mermaid
flowchart TB
  subgraph D["DynamoDB table: endpoints"]
    T["Primary key: endpoint_id<br/>Fields: url, interval_sec, state<br/>Fields: schedule_bucket, next_check_at"]
  end

  subgraph G["GSI: gsi_due_checks"]
    I["Partition key: schedule_bucket<br/>Sort key: next_check_at"]
  end

  D -->|"Indexed by"| G

  subgraph W["Multiple workers using bucket ranges"]
    W1["Worker A<br/>buckets 0 to 3"]
    W2["Worker B<br/>buckets 4 to 7"]
    W3["Worker C<br/>buckets 8 to 11"]
    W4["Worker D<br/>buckets 12 to 15"]
  end

  W1 -->|"Query due items"| G
  W2 -->|"Query due items"| G
  W3 -->|"Query due items"| G
  W4 -->|"Query due items"| G

  N["Query per bucket<br/>schedule_bucket = b<br/>next_check_at <= now<br/>Avoids table scan"]
  G --> N

  classDef data fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px;
  classDef worker fill:#fff3e0,stroke:#ef6c00,stroke-width:1px;
  classDef note fill:#e3f2fd,stroke:#1565c0,stroke-width:1px;

  class D,G,T,I data;
  class W,W1,W2,W3,W4 worker;
  class N note;
```

**Why this scales**

* No full table scans
* Efficient `Query` using GSI
* Horizontal scaling by adding workers
* No duplicate checks when bucket ranges don’t overlap

---

## 7. Health Evaluation Logic

An endpoint is marked **unhealthy** if:

* Request times out
* Network or DNS error occurs
* HTTP status code is unexpected
* Latency exceeds threshold (optional)
* Response body validation fails (optional)

State transitions are controlled by:

* `failure_threshold`
* `recovery_threshold`

---

## 8. Handling Missed Schedules

If a worker runs late or is temporarily unavailable:

* Endpoints with `next_check_at <= now` are still picked up
* Only one check is performed (no backlog storm)
* `next_check_at` is rescheduled relative to current time

This ensures eventual consistency without overloading the system.

---

## 9. Notifications

* Implemented using **Amazon SNS (Email)**
* Alert sent only on state transitions
* Continuous failures do **not** trigger repeated emails

---

## 10. Infrastructure & Security

### AWS Services Used

* ECS Fargate (compute)
* DynamoDB (state storage)
* EventBridge (scheduler)
* SNS (notifications)
* CloudWatch Logs (observability)

### Security Principles

* Least-privilege IAM roles
* No hardcoded credentials
* Scoped access to specific resources

---

## 11. Deployment Instructions

### Prerequisites

* AWS account (Free Tier sufficient)
* AWS CLI configured
* Terraform
* Docker

### Deploy Infrastructure

```
cd terraform
terraform init
terraform apply -var="sns_email=you@example.com"
```

Confirm SNS email subscription when prompted.

### Build & Push Docker Image

```
docker build -t api-health-monitor ./app
docker tag api-health-monitor:latest <ECR_URL>:latest
docker push <ECR_URL>:latest
```

---

## 12. Trade-offs & Assumptions

* Default VPC used for simplicity
* Best-effort scheduling (not real-time guarantees)
* No UI provided (focus on backend & infra)
* Bucket partitioning preferred over locking for simplicity

---

## 13. Future Improvements

* SQS-based work queue for very large scale
* Webhook or Slack notifications
* Dashboard for health history
* Alert cooldown and escalation policies
* Per-endpoint SLA tracking

---

## 14. Conclusion

This system demonstrates a **production-oriented approach** to API health monitoring, emphasizing:

* scalability
* reliability
* operational clarity
* thoughtful infrastructure design

The solution prioritizes **engineering judgment over feature completeness**, in line with the assignment goals.

---
