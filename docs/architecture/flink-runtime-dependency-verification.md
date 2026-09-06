# Flink Runtime Dependency Verification

This document defines fail-closed startup verification for Flink session cluster runtime dependencies.

## Goal

Prevent green deployment with red runtime by ensuring required connectors and credentials are validated at startup.

## Implemented Artifacts

- Image build context:
  - `services/flink-session-image/Dockerfile`
- Startup preflight script:
  - `services/flink-session-image/preflight/check_flink_runtime_deps.py`
- Entrypoint wrapper:
  - `services/flink-session-image/preflight/entrypoint-with-preflight.sh`
- CI contract gate:
  - `scripts/check_flink_runtime_preflight_contract.py`

## Verified Runtime Dependencies

The preflight script checks:

1. Required env vars
   - `ICEBERG_CATALOG_URI`
   - `ICEBERG_WAREHOUSE_URI`
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`

2. Required JAR signatures in `/opt/flink/lib` or `/opt/flink/plugins`
   - `iceberg-flink-runtime.*.jar`
   - `nessie.*.jar`
   - `hadoop-aws.*.jar`
   - `aws-java-sdk-bundle.*.jar`

If any required item is missing and strict mode is enabled, startup exits non-zero.

## Strict Mode

- `EKB_FLINK_PREFLIGHT_STRICT=true` enforces fail-closed behavior.
- This is enabled by default in the session image Dockerfile.

## Deployment Wiring

- Base K8s Flink session and taskmanager now use `yadea-ekb-flink-session:0.1.0`.
- Helm `ekb-flink-jobs` session image also uses `yadea-ekb-flink-session:0.1.0`.

## CI Gate

Release gate now blocks if preflight wiring is broken:

- `python scripts/check_flink_runtime_preflight_contract.py`
