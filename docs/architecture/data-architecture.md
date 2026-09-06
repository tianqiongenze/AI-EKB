# Data Architecture

## 1. Data Domains

Data is partitioned by governance domain:

- Global (group-wide policies, shared standards)
- Regional (region/business-unit scope)
- Local (factory-bound data, default non-export)

## 2. Storage Responsibilities

| Engine | Role | Typical Data |
|---|---|---|
| TiDB | Relational control-plane persistence | skills, audits, harness runs, outbox events |
| Redis | Hot-path cache | policy/cache entries, route hints, ephemeral state |
| Neo4j | Graph knowledge reasoning | entities, relations, causal graph paths |
| Milvus | Vector retrieval | embeddings, semantic nearest-neighbor results |
| Pulsar | Event backbone | skill lifecycle events, audits, observability events |

## 3. TiDB-Centric Control Plane Schema

Core persistence modules:

- `skill_versions`
- `audit_logs`
- `harness_runs`
- `outbox_events`

Migration baseline and migrator:

- `src/enterprise_ekb/migrations/0001_init_tidb.sql`
- `src/enterprise_ekb/migrator.py`

## 4. Event Data Flow (Outbox Pattern)

1. Business transaction commits control-plane state + outbox row
2. Relay scans pending rows
3. Publisher sends to Pulsar topic
4. Status transitions: `pending -> published` or `pending -> dead`

This design avoids dual-write inconsistency between DB and event bus.

## 5. Data Governance and Compliance Controls

- Mandatory metadata fields at knowledge-object level
- Policy checks before cross-domain tool/data operations
- Audit-first persistence of sensitive operations
- Secret and credential values kept outside Git-tracked non-secret configs

## 6. Data Quality and Lifecycle

- Versioned skill records and promotion history
- Harness outcomes tied to release gate decisions
- Dead-event tracking for operational compensation
- Optional retention policies by domain and compliance level
