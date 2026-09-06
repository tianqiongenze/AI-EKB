# Lakehouse + Streaming + Data Flywheel Architecture

## Why this is needed in this project

The current platform already has:

- high-volume connector ingestion (`src/enterprise_ekb/connectors.py`)
- reliable event backbone with outbox + Pulsar (`src/enterprise_ekb/event_bus.py`)
- governance/audit/harness control-plane data (`src/enterprise_ekb/storage.py`)

This makes Iceberg + Flink + Flywheel a natural next step for industrial-scale efficiency.

## Priority scenarios to enable

1. **Factory quality drift detection**
   - Inputs: MES/SCADA + ticketing events
   - Need: historical trend joins + real-time anomaly windows
   - Value: faster root-cause diagnosis, less downtime

2. **Supply chain delay early warning**
   - Inputs: ERP orders, inventory deltas, incident tickets
   - Need: streaming enrichment and lag KPI rollups
   - Value: proactive dispatch and SLA stability

3. **Agent governance optimization**
   - Inputs: MCP invoke audit + harness evaluation + A2A task outcomes
   - Need: offline replay + policy/harness tuning feedback loops
   - Value: lower false deny/false allow, safer automation

4. **Sub-Agent efficiency flywheel**
   - Inputs: sub-agent lifecycle states and failure/retry patterns
   - Need: retry strategy optimization and worker specialization
   - Value: higher completion ratio and lower latency

## Target architecture (enterprise baseline)

1. **Bronze layer (raw append)**
   - Pulsar topics -> Flink streaming ingest -> Iceberg raw tables
   - Partition keys: `tenant_id`, `region_id`, `event_date`

2. **Silver layer (cleaned, deduped)**
   - Flink ETL with idempotency keys and watermark rules
   - Record-level quality tags and schema-evolution-safe writes

3. **Gold layer (business marts)**
   - Domain KPI tables: quality, manufacturing, aftersales, governance
   - Optimized for BI + near-real-time decision services

4. **Data flywheel loop**
   - Ingest -> Transform -> Train -> Serve -> Feedback
   - Feedback emits `flywheel.event.recorded`
   - Governance service consumes metrics to tune policy and routing

## Implementation assets landed in this repo

- API contracts:
  - `POST /datalake/tables/register`
  - `POST /flink/pipelines/register`
  - `POST /flywheel/events`
- Pulsar topic contract extensions:
  - `datalake.table.registered`
  - `flink.pipeline.registered`
  - `flywheel.event.recorded`
- Typed schemas for DataLake/Flink/Flywheel requests

## Operational standards

- Exactly-once intent: Flink checkpoint + idempotency key at sink
- Iceberg governance: schema evolution additive-first, partition by tenant/region/date
- Cost controls: compaction windows, retention policies, cold-tier archiving
- Isolation: tenant+region quotas and namespace/topic boundaries

## Rollout plan

1. Start with connector pull and MCP/harness/a2a streams into Bronze Iceberg tables.
2. Add Silver dedup + standardization jobs for top 2 domains (quality, manufacturing).
3. Add Gold marts and SLO dashboards.
4. Enable closed-loop flywheel automation in staged mode (recommendation-only -> enforced).
