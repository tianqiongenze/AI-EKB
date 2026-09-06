#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Please install Docker and retry." >&2
  exit 1
fi

if ! command -v docker-compose >/dev/null 2>&1; then
  echo "docker-compose is required. Please install docker-compose and retry." >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR/infra"

docker-compose -f docker-compose.phase3.yml up -d

echo "Yadea EKB stack deployed."
