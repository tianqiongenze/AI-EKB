# A2A Supervision Beyond Prometheus

This document defines enterprise-grade supervision controls for A2A runtime beyond metrics scraping.

## Objectives

- Compliance-grade auditability for A2A control and runtime actions
- SIEM-ready alert streams for anomaly and incident workflows
- Tamper-resistant supervision evidence and replayability

## Supervision Layers

1. **Metrics (Prometheus)**
   - latency, throughput, error rates, dead-letter counts

2. **Audit + Event Governance (non-Prometheus)**
   - `a2a.supervision.scan.executed`
   - `a2a.supervision.alerted`
   - persistent outbox status inspection and audit query evidence

3. **SIEM forwarding**
   - route supervision events and audit records to SIEM pipeline
   - retain immutable incident timelines by correlation_id/trace_id

4. **Runbook automation**
   - critical threshold breaches trigger incident workflow hooks
   - maintain triage, escalation, and recovery checkpoints

## Implemented Controls in This Repo

- Endpoint: `POST /a2a/supervision/scan`
  - scans outbox + audit evidence window
  - detects dead-event threshold breaches
  - detects high sub-agent failure ratio
  - emits supervision scan and alert events to Pulsar contracts

- Contract/Event additions:
  - `a2a.supervision.scan.executed`
  - `a2a.supervision.alerted`

- Security controls:
  - bearer auth required on supervision endpoint
  - bounded request parameters and threshold gates

## Recommended SIEM Mapping

- `alert_type` -> detection rule category
- `severity` -> incident priority
- `details.dead_events` / `details.ratio` -> triage hints
- `summary` -> compliance report payload snapshot

## SLO and Governance Gates

- Use replay e2e load test + `scripts/check_replay_e2e_slo.py`
- Add CI gate to block release if supervision signal quality degrades
- Treat dead-event spikes as release blocker for production windows
