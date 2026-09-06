# Storage Design & Implementation Index

This directory contains concrete storage-layer design/implementation artifacts required for production-grade review and public sharing.

## Files

- `sql-ddl-spec.md`
  - TiDB SQL table/index specification aligned to migration baseline
- `cache-keys.md`
  - Redis cache key taxonomy, value shape, TTL, invalidation
- `vector-schema.md`
  - Milvus collection schema and index/search baseline
- `graph-schema.md`
  - Neo4j node/edge model and Cypher upsert baseline
- `implementation-mappings.md`
  - Matrix from storage design artifacts to code and tests

Related contract file:

- `contracts/pulsar-topics.yaml`
- `contracts/a2a-protocol.yaml`

Related API contract file:

- `contracts/openapi/control-plane.openapi.yaml`
