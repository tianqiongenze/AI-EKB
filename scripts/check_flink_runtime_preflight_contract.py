from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "services" / "flink-session-image" / "preflight" / "entrypoint-with-preflight.sh"
PREFLIGHT = ROOT / "services" / "flink-session-image" / "preflight" / "check_flink_runtime_deps.py"
DOCKERFILE = ROOT / "services" / "flink-session-image" / "Dockerfile"
RUNTIME_BOOTSTRAP = ROOT / "scripts" / "bootstrap_deploy_runtime.sh"


def run() -> int:
    if not ENTRYPOINT.exists() or not PREFLIGHT.exists() or not DOCKERFILE.exists() or not RUNTIME_BOOTSTRAP.exists():
        print("[flink-preflight-contract] FAILED")
        print("- missing preflight/runtime bootstrap artifacts for flink session image")
        return 1

    dockerfile_content = DOCKERFILE.read_text(encoding="utf-8")
    if "check_flink_runtime_deps.py" not in dockerfile_content:
        print("[flink-preflight-contract] FAILED")
        print("- Dockerfile does not include runtime dependency preflight script")
        return 1

    entrypoint_content = ENTRYPOINT.read_text(encoding="utf-8")
    if "check_flink_runtime_deps.py" not in entrypoint_content:
        print("[flink-preflight-contract] FAILED")
        print("- entrypoint does not invoke preflight check")
        return 1

    if "python3" not in dockerfile_content:
        print("[flink-preflight-contract] FAILED")
        print("- Dockerfile does not ensure python3 runtime for preflight")
        return 1

    if "iceberg-flink-runtime" not in dockerfile_content or "hadoop-aws" not in dockerfile_content:
        print("[flink-preflight-contract] FAILED")
        print("- Dockerfile does not provide required runtime jar signatures")
        return 1

    print("[flink-preflight-contract] PASS")
    print("- dockerfile, preflight, and entrypoint are wired")
    return 0


if __name__ == "__main__":
    sys.exit(run())
