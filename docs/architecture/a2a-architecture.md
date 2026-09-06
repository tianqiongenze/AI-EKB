# A2A Architecture (Yadea EKB)

## 1. Purpose

Provide an industrial-grade Agent-to-Agent (A2A) communication layer for large-scale orchestration, with explicit envelopes, idempotency, and auditability.

## 2. Envelope Contract

See: `contracts/a2a-protocol.yaml`

Key fields:

- `message_id`, `correlation_id`
- `tenant_id`, `region_id`, `plant_id`
- `agent_id`, `target_agent`, `intent`
- `priority`, `idempotency_key`, `ttl_seconds`

## 3. Transport & Routing Strategy

- Primary transport: Pulsar
- Topic pattern: `persistent://{tenant}/a2a/{region}/{target_agent}`
- Priority topic suffix for urgent events

## 4. Reliability & Ordering

- Delivery: at-least-once
- Ordering: per-agent sequence (enforced by consumer logic)
- Deduplication: `idempotency_key`
- Dead-letter on repeated failure

## 5. Control vs Data Plane

- Control plane manages agent registry, policies, and lifecycle
- Data plane handles A2A runtime messaging and processing

## 6. Observability

- Correlation ID must be propagated to audit events
- A2A events should be traceable across Pulsar topics

## 7. Security Controls

- Agent identity verification
- Tenant/region isolation enforced at topic boundary
- Payload data minimized and optionally encrypted
