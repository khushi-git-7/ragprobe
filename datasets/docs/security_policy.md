# Northwind Robotics Information Security Policy

A fictional security policy used as part of the RAGProbe sample corpus.

## Data Encryption

All customer data is encrypted in transit using TLS 1.3 and at rest using AES-256.
Encryption keys are managed in a hardware security module and rotated every 90
days. Backups are encrypted with the same standard and are stored in a separate
geographic region from the primary data store.

## Access Control

Access to production systems follows the principle of least privilege. All
production access requires multi-factor authentication and is granted through
short-lived credentials that expire after 8 hours. Access reviews are performed
quarterly by the security team, and any account inactive for 60 days is
automatically disabled.

## Incident Response

Security incidents are triaged within 1 hour of detection. Customers affected by a
confirmed data breach are notified within 72 hours. The incident response team
maintains a runbook for each incident class and conducts a blameless post-mortem
within 5 business days of resolution.

## Data Retention

Telemetry data is retained for 13 months and then permanently deleted. Application
logs are retained for 90 days. Customer account records are retained for the
duration of the contract plus 7 years to satisfy financial reporting obligations.
Customers may request earlier deletion of telemetry data through a support ticket.

## Vulnerability Management

Third-party penetration tests are commissioned annually. Critical vulnerabilities
must be remediated within 7 days of discovery, high severity within 30 days, and
medium severity within 90 days. Dependency scanning runs on every pull request and
blocks merges that introduce a known critical vulnerability.
