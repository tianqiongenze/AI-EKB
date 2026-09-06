# Graph Schema and Model Design (Neo4j)

## 1. Scope

Defines Neo4j graph model baseline, relationship semantics, and implementation mapping for KGraph reasoning.

## 2. Node Model

Current baseline node label: `Entity`

| Property | Type | Description |
|---|---|---|
| `id` | string | Stable entity identifier |
| `tenant_id` | string | Tenant boundary (recommended extension) |
| `region_id` | string | Regional boundary (recommended extension) |
| `plant_id` | string | Site boundary (recommended extension) |
| `type` | string | Entity type (equipment, process, issue, etc.) |

## 3. Relationship Model

Current baseline relationship type: `RELATED`

| Property | Type | Description |
|---|---|---|
| `type` | string | Semantic relation category |
| `weight` | number | Optional confidence/importance weight |
| `source` | string | Optional provenance |

## 4. Cypher Upsert Baseline

Implementation query pattern in code:

```cypher
UNWIND $rows AS row
MERGE (a:Entity {id: row.source})
MERGE (b:Entity {id: row.target})
MERGE (a)-[r:RELATED {type: row.relation_type}]->(b)
```

Implementation mapping:

- `HighPerformanceNeo4jClient.batch_upsert_relations(...)`

## 5. Query and Reasoning Guidance

- Use bounded traversal depth for predictable latency
- Prefer parameterized queries only
- Keep write batches moderate to avoid long transactions

## 6. Governance and Isolation

- Recommended: include tenant/region/plant attributes on nodes and query predicates
- Maintain relation provenance for explainability and audit trace
