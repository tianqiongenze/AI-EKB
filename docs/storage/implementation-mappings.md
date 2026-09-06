# Storage Implementation Mapping Matrix

## 1. Purpose

This document bridges design intent and implementation artifacts for all storage layers before production release.

## 2. Matrix

| Layer | Design Artifact | Implementation Artifact | Test/Verification Artifact |
|---|---|---|---|
| SQL / Relational (TiDB) | `docs/storage/sql-ddl-spec.md` | `src/enterprise_ekb/tidb_store.py`, `src/enterprise_ekb/migrations/0001_init_tidb.sql`, `src/enterprise_ekb/migrator.py` | `tests/test_storage_and_outbox.py`, `tests/test_config_and_tidb_selection.py` |
| Cache (Redis) | `docs/storage/cache-keys.md` | `src/enterprise_ekb/middleware_clients.py` (`HighPerformanceRedisClient`) | gateway behavior + Python tests baseline |
| Message Queue (Pulsar) | `contracts/pulsar-topics.yaml`, `docs/phase2-eventing-and-sre.md` | `src/enterprise_ekb/event_bus.py`, `src/enterprise_ekb/middleware_clients.py` (`HighPerformancePulsarClient`) | `tests/test_pulsar_publisher.py` |
| A2A Protocol | `contracts/a2a-protocol.yaml`, `docs/architecture/a2a-architecture.md` | `src/enterprise_ekb/app.py` (`/a2a/publish`), `src/enterprise_ekb/schemas.py` | `tests/test_a2a_publish.py` |
| Vector Store (Milvus) | `docs/storage/vector-schema.md` | `src/enterprise_ekb/middleware_clients.py` (`HighPerformanceMilvusClient`) | retrieval path verification in integration stage |
| Graph Store (Neo4j) | `docs/storage/graph-schema.md` | `src/enterprise_ekb/middleware_clients.py` (`HighPerformanceNeo4jClient`), Java KGraph service | Java tests + graph integration in staging |
| API Contract | `contracts/openapi/control-plane.openapi.yaml` | `src/enterprise_ekb/app.py` endpoints and payload models | `tests/test_app_phase2.py`, `tests/test_health_and_capacity.py` |
| Graph/Vector API | `docs/storage/vector-schema.md`, `docs/storage/graph-schema.md` | `src/enterprise_ekb/app.py` (`/graph/upsert`, `/vector/upsert`, `/vector/search`) | integration stage |

## 3. Release Completeness Checklist

- [x] SQL migration baseline present
- [x] Cache key taxonomy documented
- [x] Pulsar topic contract formally documented
- [x] Pulsar topic contract aligned with emitted payload shape
- [x] Vector schema/index baseline documented
- [x] Graph schema/model and Cypher baseline documented
- [x] Mapping document connects design to code/tests
- [x] A2A envelope and topic contract documented
