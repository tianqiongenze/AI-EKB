#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT_DIR/scripts/colima_runtime.sh"

ensure_colima_runtime

pull_with_fallback() {
  local target="$1"
  shift
  local sources=("$@")
  local ok=0
  for src in "${sources[@]}"; do
    for attempt in 1 2 3 4 5; do
      echo "[prefetch] trying $src (attempt $attempt/5)"
      if docker pull "$src"; then
        docker tag "$src" "$target"
        echo "[prefetch] tagged $src -> $target"
        ok=1
        break
      fi
      sleep 3
    done
    if [[ "$ok" -eq 1 ]]; then
      break
    fi
  done
  if [[ "$ok" -ne 1 ]]; then
    echo "[prefetch] failed to resolve image for $target"
    return 1
  fi
}

pull_with_fallback "ekb-mirror/pingcap-tidb:v8.5.5" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/pingcap/tidb:v8.5.5" \
  "docker.m.daocloud.io/pingcap/tidb:v8.5.5" \
  "docker.io/pingcap/tidb:v8.5.5"

pull_with_fallback "ekb-mirror/pingcap-pd:v8.5.5" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/pingcap/pd:v8.5.5" \
  "docker.m.daocloud.io/pingcap/pd:v8.5.5" \
  "docker.io/pingcap/pd:v8.5.5"

pull_with_fallback "ekb-mirror/pingcap-tikv:v8.5.5" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/pingcap/tikv:v8.5.5" \
  "docker.m.daocloud.io/pingcap/tikv:v8.5.5" \
  "docker.io/pingcap/tikv:v8.5.5"

pull_with_fallback "ekb-mirror/redis:7" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/redis:7" \
  "docker.m.daocloud.io/library/redis:7" \
  "docker.io/library/redis:7"

pull_with_fallback "ekb-mirror/neo4j:5.25.1-community-bullseye" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/neo4j:5.25.1-community-bullseye" \
  "docker.m.daocloud.io/neo4j:5.25.1-community-bullseye" \
  "docker.io/neo4j:5.25.1-community-bullseye"

pull_with_fallback "ekb-mirror/milvus:v2.4.4" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/milvusdb/milvus:v2.4.4" \
  "docker.m.daocloud.io/milvusdb/milvus:v2.4.4" \
  "docker.io/milvusdb/milvus:v2.4.4"

pull_with_fallback "ekb-mirror/pulsar:3.2.3" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/apachepulsar/pulsar:3.2.3" \
  "docker.m.daocloud.io/apachepulsar/pulsar:3.2.3" \
  "docker.io/apachepulsar/pulsar:3.2.3"

pull_with_fallback "ekb-mirror/maven:3.9-eclipse-temurin-21" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/maven:3.9-eclipse-temurin-21" \
  "docker.m.daocloud.io/library/maven:3.9-eclipse-temurin-21" \
  "docker.io/library/maven:3.9-eclipse-temurin-21"

pull_with_fallback "ekb-mirror/golang:1.22" \
  "docker.m.daocloud.io/library/golang:1.22" \
  "docker.io/library/golang:1.22"

pull_with_fallback "kindest/node:v1.35.0" \
  "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/kindest/node:v1.35.0" \
  "docker.m.daocloud.io/kindest/node:v1.35.0" \
  "docker.io/kindest/node:v1.35.0"

echo "[prefetch] done"
