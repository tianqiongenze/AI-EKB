# Developer API Manual (Yadea EKB)

## 1. Overview

This manual describes the control-plane APIs for Yadea EKB, including governance, A2A, graph, and vector operations.

Base URL: `http://<host>:8080`

Authentication: Bearer token via `Authorization: Bearer <EKB_AUTH_TOKEN>` (when configured).

## 2. Health

- `GET /healthz`
- `GET /readyz`

## 3. Skill Lifecycle

- `POST /skills/register`
- `POST /skills/promote`

## 4. MCP Gateway

- `POST /mcp/invoke`
  - Policy checks: stage/tool/domain/residency
  - Audit record + event to Pulsar

## 5. Harness

- `POST /harness/evaluate`

## 6. Capacity Planning

- `POST /capacity/estimate`

## 7. Audit

- `POST /audit/query`

## 8. Event Relay

- `POST /events/relay`

## 9. A2A Messaging

- `POST /a2a/publish`
- `POST /a2a/consume`

## 10. Graph API

- `POST /graph/upsert`
  - 依赖 Neo4j 服务；不可用时返回 503

## 11. Vector API

- `POST /vector/upsert`
- `POST /vector/search`
  - 依赖 Milvus 服务；不可用时返回 503

## 12. Contracts

- OpenAPI: `contracts/openapi/control-plane.openapi.yaml`
- Pulsar Topics: `contracts/pulsar-topics.yaml`
- A2A Protocol: `contracts/a2a-protocol.yaml`
