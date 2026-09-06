#!/usr/bin/env bash
set -euo pipefail

ensure_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[colima-runtime] missing required command: $cmd"
    exit 1
  fi
}

ensure_colima_runtime() {
  ensure_cmd colima
  ensure_cmd docker

  if ! colima status >/dev/null 2>&1; then
    colima start
  fi

  docker context use colima >/dev/null

  if ! docker info >/dev/null 2>&1; then
    echo "[colima-runtime] docker daemon unavailable on colima context"
    exit 1
  fi
}

ensure_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    return 0
  fi
  echo "[colima-runtime] neither 'docker compose' nor 'docker-compose' is available"
  exit 1
}

ensure_buildx() {
  if docker buildx version >/dev/null 2>&1; then
    return 0
  fi
  echo "[colima-runtime] docker buildx plugin unavailable"
  exit 1
}
