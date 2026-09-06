# SQL DDL Specification (TiDB Control Plane)

## 1. Scope

This specification mirrors the current TiDB migration baseline and provides release-review visibility at SQL detail level.

Source migration:

- `src/enterprise_ekb/migrations/0001_init_tidb.sql`

## 2. Tables

### 2.1 `schema_migrations`

- Tracks applied schema versions.

### 2.2 `skills`

- Primary key: `(skill_name, version)`
- Stores ownership, risk/stage, allowed tools/domains, IO schema, changelog.

### 2.3 `audits`

- Primary key: `id`
- Indexed on `(tenant_id, created_at)` for audit query paths.
- Stores governance decisions and payload snapshots.

### 2.4 `harness_runs`

- Primary key: `id`
- Indexed on `(tenant_id, created_at)`.
- Stores quality/safety/regression scores and accept/reject output.

### 2.5 `outbox_events`

- Primary key: `id`
- Indexed on `(status, id)` for relay scanning.
- Stores event payload and publication lifecycle (`pending/published/dead`).

## 3. Indexing and Query Intent

- Audit and harness query APIs are tenant/time oriented.
- Outbox relay scans by status + monotonic ID.

## 4. Evolution Rules

1. Never mutate schema manually in production.
2. Add new migration version file for each compatible change.
3. For incompatible changes, use phased rollout and dual-read/dual-write strategy if needed.
