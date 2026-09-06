#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ARTIFACT_DIR="$ROOT_DIR/perf/artifacts/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ARTIFACT_DIR"

echo "[perf] artifact dir: $ARTIFACT_DIR"

source "$ROOT_DIR/scripts/colima_runtime.sh"
ensure_colima_runtime
ensure_docker_compose
ensure_buildx
bash "$ROOT_DIR/scripts/colima_registry_setup.sh"
bash "$ROOT_DIR/scripts/prefetch_colima_images.sh"

if ! command -v k6 >/dev/null 2>&1; then
  echo "[perf] k6 command not found"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[perf] neither 'docker compose' nor 'docker-compose' is available"
  exit 1
fi

COMPOSE_FILE="${PERF_COMPOSE_FILE:-$ROOT_DIR/infra/docker-compose.phase3.colima.yml}"
if [[ -n "${PERF_COMPOSE_SERVICES:-}" ]]; then
  IFS=' ' read -r -a PERF_SERVICES <<<"$PERF_COMPOSE_SERVICES"
else
  PERF_SERVICES=(
    etcd
    pd
    tikv
    tidb
    redis
    pulsar
    ekb-python-control-plane
    ekb-go-gateway
  )
fi

attempt=1
max_attempts=3

if [[ "$COMPOSE_FILE" == *"docker-compose.phase3.yml"* || "$COMPOSE_FILE" == *"docker-compose.phase3.colima.yml"* ]]; then
  export TIDB_IMAGE="${TIDB_IMAGE:-ekb-mirror/pingcap-tidb:v8.5.5}"
  export PD_IMAGE="${PD_IMAGE:-ekb-mirror/pingcap-pd:v8.5.5}"
  export TIKV_IMAGE="${TIKV_IMAGE:-ekb-mirror/pingcap-tikv:v8.5.5}"
fi

export REDIS_IMAGE="${REDIS_IMAGE:-ekb-mirror/redis:7}"
export NEO4J_IMAGE="${NEO4J_IMAGE:-ekb-mirror/neo4j:5.25.1-community-bullseye}"
export MILVUS_IMAGE="${MILVUS_IMAGE:-ekb-mirror/milvus:v2.4.4}"
export PULSAR_IMAGE="${PULSAR_IMAGE:-ekb-mirror/pulsar:3.2.3}"
export GOLANG_IMAGE="${GOLANG_IMAGE:-ekb-mirror/golang:1.22}"
export MAVEN_IMAGE="${MAVEN_IMAGE:-ekb-mirror/maven:3.9-eclipse-temurin-21}"

until "${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" up -d --build "${PERF_SERVICES[@]}"; do
  if [[ "$attempt" -ge "$max_attempts" ]]; then
    echo "[perf] compose up failed after $attempt attempts"
    exit 1
  fi
  echo "[perf] compose up failed, retrying ($attempt/$max_attempts) ..."
  attempt=$((attempt + 1))
  sleep 10
done

curl --retry 30 --retry-delay 2 --retry-connrefused --retry-all-errors http://127.0.0.1:8080/healthz > "$ARTIFACT_DIR/healthz.json"
curl --retry 30 --retry-delay 2 --retry-connrefused --retry-all-errors http://127.0.0.1:8080/readyz > "$ARTIFACT_DIR/readyz.json"
curl --retry 30 --retry-delay 2 --retry-connrefused --retry-all-errors http://127.0.0.1:8090/healthz > "$ARTIFACT_DIR/gateway-healthz.json"

set +e
k6 run "$ROOT_DIR/perf/k6/replay-e2e-load-test.js" --summary-export "$ARTIFACT_DIR/replay-e2e-summary.json" > "$ARTIFACT_DIR/replay-e2e.log" 2>&1
replay_exit=$?
k6 run "$ROOT_DIR/perf/k6/load-test.js" --summary-export "$ARTIFACT_DIR/long-soak-summary.json" > "$ARTIFACT_DIR/long-soak.log" 2>&1
soak_exit=$?
set -e

"${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" logs "${PERF_SERVICES[@]}" > "$ARTIFACT_DIR/compose.log"

echo "[perf] completed"
echo "[perf] artifacts: $ARTIFACT_DIR"

if [[ $replay_exit -ne 0 || $soak_exit -ne 0 ]]; then
  echo "[perf] k6 failed: replay_exit=$replay_exit soak_exit=$soak_exit"
  exit 1
fi
