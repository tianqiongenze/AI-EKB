#!/usr/bin/env bash
set -euo pipefail

python3 /opt/ekb/preflight/check_flink_runtime_deps.py

if [ "$#" -eq 0 ]; then
  exec /docker-entrypoint.sh jobmanager
else
  exec /docker-entrypoint.sh "$@"
fi
