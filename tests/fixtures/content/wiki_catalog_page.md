---
owner: data-platform-team
domain: commerce
tags:
  - orders
  - transactions
  - pii
---

# Customer Orders

Daily snapshot of all customer orders from the Sony commerce platform.

## Description
Aggregated order data joined from the transactional database. Refreshed at 02:00 UTC daily.

## Owner
data-platform-team

## Domain
commerce

## Upstream
- `orders_raw` (Snowflake)
- `customers_dim` (Snowflake)

## Downstream
- `revenue_daily` dashboard
- `churn_risk_model` ML pipeline
