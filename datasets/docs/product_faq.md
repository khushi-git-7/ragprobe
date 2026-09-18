# Northwind Fleet Platform - Frequently Asked Questions

Northwind Fleet is the fictional fleet-management product used in the RAGProbe sample corpus.

## What Is Northwind Fleet

Northwind Fleet is a fleet management platform for autonomous warehouse robots. It provides
live telemetry, task scheduling, battery management and a simulation environment
for testing routing changes before they reach production hardware.

## Pricing Tiers

Northwind Fleet is sold in three tiers. The Starter tier costs 99 USD per month and supports
up to 10 robots. The Growth tier costs 499 USD per month and supports up to 100
robots. The Enterprise tier is priced on request and has no robot limit. All tiers
are billed monthly in arrears and include unlimited user seats.

## API Rate Limits

The Northwind Fleet REST API allows 1000 requests per minute on the Starter tier, 5000
requests per minute on the Growth tier, and a negotiated limit on Enterprise.
Exceeding the limit returns HTTP 429 with a Retry-After header. Rate limits are
applied per organisation, not per API key.

## Supported Integrations

Northwind Fleet integrates with ChatRelay, PageWatch, MetricHub, DataVault and generic webhooks.
The ChatRelay integration posts fleet alerts to a channel of your choice. The
DataVault integration exports telemetry once per hour. Custom integrations can be
built against the public REST API and the streaming WebSocket feed.

## Data Export

Customers can export their telemetry data at any time in CSV or Parquet format.
Exports are generated asynchronously and a download link is emailed when the
archive is ready. Export archives remain available for 7 days. There is no charge
for data export on any tier.
