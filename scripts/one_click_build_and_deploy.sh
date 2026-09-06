#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-local}"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

source "$ROOT_DIR/scripts/colima_runtime.sh"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.11)"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "[one-click] python runtime not found"
    exit 1
  fi
fi

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[one-click] missing required command: $cmd"
    exit 1
  fi
}

wait_http_ready() {
  local name="$1"
  local url="$2"
  local timeout_seconds="${3:-180}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[one-click] ${name} is ready: ${url}"
      return 0
    fi

    local now
    now="$(date +%s)"
    if (( now - started_at >= timeout_seconds )); then
      echo "[one-click] timeout waiting for ${name}: ${url}"
      return 1
    fi

    sleep 2
  done
}

init_local_tidb_database() {
  local timeout_seconds="${1:-240}"
  local started_at
  started_at="$(date +%s)"

  while true; do
    if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import pymysql

conn = pymysql.connect(
    host="127.0.0.1",
    port=4000,
    user="root",
    password="",
    connect_timeout=3,
    read_timeout=3,
    write_timeout=3,
)
try:
    with conn.cursor() as cur:
        cur.execute("CREATE DATABASE IF NOT EXISTS ekb_control_plane")
    conn.commit()
finally:
    conn.close()
PY
    then
      echo "[one-click] TiDB database initialized: ekb_control_plane"
      return 0
    fi

    local now
    now="$(date +%s)"
    if (( now - started_at >= timeout_seconds )); then
      echo "[one-click] timeout initializing TiDB database ekb_control_plane"
      return 1
    fi

    sleep 2
  done
}

run_local() {
  ensure_colima_runtime
  ensure_docker_compose
  ensure_buildx
  bash "$ROOT_DIR/scripts/prefetch_colima_images.sh"
  export TIDB_IMAGE="${TIDB_IMAGE:-ekb-mirror/pingcap-tidb:v8.5.5}"
  export PD_IMAGE="${PD_IMAGE:-ekb-mirror/pingcap-pd:v8.5.5}"
  export TIKV_IMAGE="${TIKV_IMAGE:-ekb-mirror/pingcap-tikv:v8.5.5}"
  export REDIS_IMAGE="${REDIS_IMAGE:-ekb-mirror/redis:7}"
  export NEO4J_IMAGE="${NEO4J_IMAGE:-ekb-mirror/neo4j:5.25.1-community-bullseye}"
  export MILVUS_IMAGE="${MILVUS_IMAGE:-ekb-mirror/milvus:v2.4.4}"
  export PULSAR_IMAGE="${PULSAR_IMAGE:-ekb-mirror/pulsar:3.2.3}"
  export GOLANG_IMAGE="${GOLANG_IMAGE:-ekb-mirror/golang:1.22}"
  export MAVEN_IMAGE="${MAVEN_IMAGE:-ekb-mirror/maven:3.9-eclipse-temurin-21}"
  local compose_cmd=(docker compose -f "$ROOT_DIR/infra/docker-compose.phase3.colima.yml")
  if command -v docker-compose >/dev/null 2>&1; then
    compose_cmd=(docker-compose -f "$ROOT_DIR/infra/docker-compose.phase3.colima.yml")
  fi

  "${compose_cmd[@]}" up -d \
    etcd pd tikv tidb redis neo4j milvus pulsar

  init_local_tidb_database 240

  "${compose_cmd[@]}" up -d --build \
    ekb-python-control-plane ekb-java-kgraph ekb-go-gateway

  wait_http_ready "control-plane healthz" "http://127.0.0.1:8080/healthz" 240
  wait_http_ready "control-plane readyz" "http://127.0.0.1:8080/readyz" 240
  wait_http_ready "go-gateway healthz" "http://127.0.0.1:8090/healthz" 180
}

run_k8s() {
  ensure_colima_runtime
  ensure_docker_compose
  ensure_buildx
  bash "$ROOT_DIR/scripts/prefetch_colima_images.sh"
  require_cmd kubectl
  require_cmd helm

  FLINK_IMAGE_REPO="${FLINK_IMAGE_REPO:-ekb-mirror}"
  FLINK_IMAGE_TAG="${FLINK_IMAGE_TAG:-local}"
  FLINK_IMAGE="${FLINK_IMAGE_REPO}/yadea-ekb-flink-session:${FLINK_IMAGE_TAG}"
  CONTROL_PLANE_IMAGE="${CONTROL_PLANE_IMAGE:-yadea-ekb:0.2.0}"
  GO_GATEWAY_IMAGE="${GO_GATEWAY_IMAGE:-yadea-ekb-go-gateway:0.2.0}"

  if [[ -z "${AWS_ACCESS_KEY_ID:-}" || -z "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
    echo "[one-click] AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set for k8s mode"
    exit 1
  fi

  if command -v kind >/dev/null 2>&1; then
    if ! kind get clusters | grep -qx "kind"; then
      kind create cluster --name kind
    fi
    kubectl config use-context kind-kind >/dev/null 2>&1 || true
  fi

  docker build -t "$CONTROL_PLANE_IMAGE" "$ROOT_DIR"
  docker build -t "$GO_GATEWAY_IMAGE" -f "$ROOT_DIR/services/go-gateway/Dockerfile" "$ROOT_DIR"
  docker build -t "$FLINK_IMAGE" "$ROOT_DIR/services/flink-session-image"

  if command -v kind >/dev/null 2>&1; then
    kind load docker-image "$FLINK_IMAGE"
    kind load docker-image "$CONTROL_PLANE_IMAGE"
    kind load docker-image "$GO_GATEWAY_IMAGE"
  fi

  kubectl apply -k "$ROOT_DIR/infra/k8s/deps"
  "$PYTHON_BIN" "$ROOT_DIR/scripts/verify_k8s_stack.py"

  kubectl apply -f "$ROOT_DIR/infra/k8s/base/service-go-gateway.yaml"
  kubectl apply -f "$ROOT_DIR/infra/k8s/base/deployment-go-gateway.yaml"
  kubectl apply -f "$ROOT_DIR/infra/k8s/base/hpa-go-gateway.yaml"
  kubectl apply -f "$ROOT_DIR/infra/k8s/base/pdb-go-gateway.yaml"
  kubectl apply -f "$ROOT_DIR/infra/k8s/base/networkpolicy-go-gateway.yaml"
  helm upgrade --install ekb-control-plane "$ROOT_DIR/infra/helm/ekb-control-plane" --namespace ekb-control-plane --create-namespace
  helm upgrade --install ekb-flink-jobs "$ROOT_DIR/infra/helm/ekb-flink-jobs" \
    --namespace ekb-control-plane \
    --set sessionCluster.image="$FLINK_IMAGE" \
    --set credentials.awsAccessKeyId="$AWS_ACCESS_KEY_ID" \
    --set credentials.awsSecretAccessKey="$AWS_SECRET_ACCESS_KEY"

  "$PYTHON_BIN" "$ROOT_DIR/scripts/verify_k8s_stack.py"
}

echo "[one-click] mode=$MODE"
cd "$ROOT_DIR"

export TIDB_IMAGE="${TIDB_IMAGE:-ekb-mirror/pingcap-tidb:v8.5.5}"
export PD_IMAGE="${PD_IMAGE:-ekb-mirror/pingcap-pd:v8.5.5}"
export TIKV_IMAGE="${TIKV_IMAGE:-ekb-mirror/pingcap-tikv:v8.5.5}"

if [[ "${SKIP_BOOTSTRAP_DEPLOY_RUNTIME:-false}" != "true" ]]; then
  bash "$ROOT_DIR/scripts/bootstrap_deploy_runtime.sh" "$MODE"
fi
if [[ "${SKIP_COLIMA_REGISTRY_SETUP:-false}" != "true" ]]; then
  bash "$ROOT_DIR/scripts/colima_registry_setup.sh"
fi
if [[ "${SKIP_BOOTSTRAP_DEV_TOOLCHAIN:-false}" != "true" ]]; then
  bash "$ROOT_DIR/scripts/bootstrap_dev_toolchain.sh"
fi
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_dev_toolchain.py"
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_contract_consistency.py"
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_flink_runtime_preflight_contract.py"
"$PYTHON_BIN" "$ROOT_DIR/scripts/check_replay_e2e_slo.py"

if [[ "$MODE" == "local" ]]; then
  run_local
elif [[ "$MODE" == "k8s" ]]; then
  run_k8s
else
  echo "[one-click] unsupported mode: $MODE"
  echo "usage: scripts/one_click_build_and_deploy.sh [local|k8s]"
  exit 1
fi

echo "[one-click] done"
