# EKB Local/K8S Pressure Test Report

## Metadata

- Date: 2026-04-02
- Environment: local compose (perf local profile, SQLite + Pulsar + Redis + Go gateway)
- Machine: macOS (Apple Silicon)
- Tester: autonomous agent run

## Deployment Summary

- Commands used:
  - `PERF_COMPOSE_FILE="infra/docker-compose.perf.local.yml" PERF_COMPOSE_SERVICES="redis pulsar ekb-python-control-plane ekb-go-gateway" bash scripts/run_local_long_perf.sh`
  - `bash scripts/run_local_long_perf.sh` (default TiDB stack attempt)
- Bootstrap status:
  - local perf profile: completed, services reachable
  - default TiDB profile: blocked by image registry availability (`docker.m.daocloud.io` pull unavailable)
- Stack verification status: `healthz/readyz/gateway-healthz` reachable before load in local perf profile

## Service Readiness

- Pulsar: ready (local perf profile)
- Redis: ready (local perf profile)
- Control plane: ready on `:8080`
- Go gateway: ready on `:8090`
- TiDB/PD/TiKV (default profile): not started due to registry pull failures

## Topic & Data Initialization

- Pulsar topic status:
  - `group` tenant/namespaces used during run; runtime publishes successfully for `mcp.invoked`/A2A/audit events.
- Contract namespace alignment work completed in code:
  - `contracts/pulsar-topics.yaml` tenancy namespaces now include `a2a` and `a2a-dlq` in addition to `control/audit/observability`.

## Pressure Test Runs

### A) Local perf profile run (artifact: `20260402-174512`)
- Result summary:
  - Soak failed hard on invoke checks.
  - Root cause: k6 setup registered/promoted skill against gateway URL, so `/mcp/invoke` path did not have valid prepared state.

### B) Local perf profile run after setup fix (artifact: `20260402-183709`)
- Result summary:
  - All endpoint checks pass (`health/route/invoke/relay` all 200).
  - `http_req_failed` improved to 0.00% and meets gate.
  - Remaining fail is latency SLO only: `ai_control_latency` p95/p99 exceed thresholds.

### C) Default TiDB profile attempt (artifact dir created: `20260402-192245`)
- Result summary:
  - Compose startup retried 3 times and failed.
  - Blocking issue: upstream registry unavailable while pulling PingCAP images.

## Key Metrics (latest successful local perf run)

- Source artifact: `perf/artifacts/20260402-183709/long-soak-summary.json`
- HTTP failed rate:
  - `http_req_failed` = **0.00%** (gate pass)
- Control-plane latency:
  - `ai_control_latency` p95 = **1139ms** (gate target `<500`, fail)
  - `ai_control_latency` p99 = **2220ms** (gate target `<1200`, fail)
- Gateway latency:
  - `gateway_latency` p95 = 4ms
  - `gateway_route_latency` p95 = 6ms
- Replay (same run set):
  - `replay-e2e` checks all pass, but replay latency thresholds remain above strict targets in summary export.

## Artifacts

- Previous failing local run:
  - `perf/artifacts/20260402-174512/`
- Latest local run (setup fixed, latency-only failure):
  - `perf/artifacts/20260402-183709/replay-e2e-summary.json`
  - `perf/artifacts/20260402-183709/long-soak-summary.json`
  - `perf/artifacts/20260402-183709/long-soak.log`
  - `perf/artifacts/20260402-183709/compose.log`
- TiDB attempt (startup blocked):
  - `perf/artifacts/20260402-192245/`

## Code Changes in This Iteration

- `src/enterprise_ekb/storage.py`
  - Completed migration of remaining write methods to `_run_write()` transaction wrapper.
  - Added shared in-memory SQLite URI mode for `:memory:` to keep thread-local connections on one shared test DB.
- `src/enterprise_ekb/app.py`
  - Added configurable retry wrappers for `/mcp/invoke` and `/events/relay` paths.
  - Added relay batch-size cap from config.
- `src/enterprise_ekb/config.py`
  - Added retry/backpressure configs for invoke/relay.
  - Normalized datalake topic default prefixes to `control/audit/observability` namespaces.
- `perf/k6/load-test.js`
  - Fixed setup to register/promote skill against `controlBaseUrl`.
  - Added setup checks for register/promote responses.
- `scripts/check_replay_e2e_slo.py`
  - Updated threshold parser to support both dotted and underscore metric naming.
- `scripts/check_contract_consistency.py`
  - Added tenancy namespace coverage check for required Pulsar namespaces.
- `contracts/pulsar-topics.yaml`
  - Added `a2a`, `a2a-dlq` under tenancy namespaces.
- `pyproject.toml`
  - Added `PyYAML` runtime dependency for contract checks.

## Conclusion

- Pass/Fail: **Fail** (latency gate not met yet)
- Major improvement achieved:
  - Functional correctness under load restored (`invoke status 200` now passes; request failure rate 0%).
- Remaining risk:
  - Control-plane p95/p99 latency is still above soak SLO under current SQLite local perf profile.
  - TiDB validation path is blocked by image pull availability from current registry mirror.

## Next actions

1. Run the same long test on TiDB-backed control-plane once image source is reachable (or switch to an accessible mirror/registry).
2. Keep current invoke/relay retry knobs and tune defaults based on TiDB run results.
3. If TiDB still misses SLO, add controlled queueing on write-heavy outbox/audit hotspots and re-benchmark.
