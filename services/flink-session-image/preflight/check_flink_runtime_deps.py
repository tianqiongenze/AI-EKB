from __future__ import annotations

import os
import re
import sys
from pathlib import Path


FLINK_LIB = Path("/opt/flink/lib")
FLINK_PLUGINS = Path("/opt/flink/plugins")


def _fail(message: str) -> int:
    print(f"[flink-preflight] FAILED: {message}")
    return 2


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"missing required env: {name}")
    return value


def _find_required_jar(pattern: str) -> bool:
    regex = re.compile(pattern)
    for base in (FLINK_LIB, FLINK_PLUGINS):
        if not base.exists():
            continue
        for file in base.rglob("*.jar"):
            if regex.search(file.name):
                return True
    return False


def run() -> int:
    strict = os.getenv("EKB_FLINK_PREFLIGHT_STRICT", "true").lower() == "true"

    required_envs = [
        "ICEBERG_CATALOG_URI",
        "ICEBERG_WAREHOUSE_URI",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ]

    missing_envs: list[str] = []
    for name in required_envs:
        try:
            _require_env(name)
        except ValueError:
            missing_envs.append(name)

    if missing_envs and strict:
        return _fail(f"missing env vars: {', '.join(missing_envs)}")

    required_jars = {
        "iceberg flink runtime": r"iceberg-flink-runtime.*\.jar",
        "iceberg nessie": r"nessie.*\.jar",
        "hadoop s3 connector": r"hadoop-aws.*\.jar",
        "aws sdk bundle": r"aws-java-sdk-bundle.*\.jar",
    }

    missing_jars: list[str] = []
    for label, pattern in required_jars.items():
        if not _find_required_jar(pattern):
            missing_jars.append(label)

    if missing_jars and strict:
        return _fail(f"missing required jars: {', '.join(missing_jars)}")

    placeholder_markers = {"replace-me", "example", "changeme", "<from-secret>"}
    weak_values: list[str] = []
    for name in required_envs:
        value = os.getenv(name, "").strip().lower()
        if any(marker in value for marker in placeholder_markers):
            weak_values.append(name)

    if weak_values and strict:
        return _fail(f"placeholder env values detected: {', '.join(weak_values)}")

    print("[flink-preflight] PASS")
    print(f"- strict mode: {strict}")
    print(f"- checked envs: {len(required_envs)}")
    print(f"- checked jar signatures: {len(required_jars)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
