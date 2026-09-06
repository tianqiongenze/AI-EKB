# Vector Schema and Index Design (Milvus)

## 1. Scope

Defines recommended collection schema, field conventions, index/search parameters, and implementation mapping for vector retrieval in EKB.

## 2. Collection Model

Recommended collection: `knowledge_chunks_v1`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string / varchar | yes | Stable chunk identifier |
| `tenant_id` | string | yes | Tenant boundary |
| `region_id` | string | yes | Residency boundary |
| `plant_id` | string | yes | Factory/site boundary |
| `domain` | string | yes | Business domain (qa, manufacturing, quality, etc.) |
| `doc_id` | string | yes | Source document ID |
| `chunk_idx` | int | yes | Chunk ordinal |
| `embedding` | float vector(1024) | yes | Dense embedding vector |
| `created_at` | timestamp/string | yes | Write timestamp |
| `effective_at` | timestamp/string | no | Governance effective time |
| `expires_at` | timestamp/string | no | Retention boundary |

## 3. Index and Search Baseline

- Metric type: `COSINE`
- Search params baseline: `{ "ef": 128 }`
- Limit: default `top_k = 10` (caller configurable)

Implementation mapping:

- `HighPerformanceMilvusClient.search(...)` uses
  - `metric_type = COSINE`
  - `params.ef = 128`

## 4. Ingestion and Upsert Rules

- Upsert should include governance metadata (`tenant_id/region_id/plant_id`)
- Chunk IDs must be deterministic to avoid duplicate drift
- Batch upserts preferred for throughput

Implementation mapping:

- `HighPerformanceMilvusClient.batch_upsert(...)`

## 5. Retrieval Guardrails

- Always filter by tenant/region/plant context in retrieval orchestration layer
- Keep vector payload separate from sensitive source content
- Log retrieval context for auditability where required

## 6. Evolution Strategy

- Introduce new collection versions (`knowledge_chunks_v2`) for incompatible schema changes
- Keep read compatibility window during migration
- Backfill asynchronously before cutover
