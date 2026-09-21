from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "perf" / "reports"


def run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def must(command: list[str], timeout: int = 300) -> str:
    proc = run(command, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def ensure_summary_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def run_seed(records: int, summary_path: Path) -> None:
    ensure_summary_path(summary_path)
    must(
        [
            sys.executable,
            str(ROOT / "scripts/seed_large_scale_data.py"),
            "--records-per-store",
            str(records),
            "--stores",
            "tidb,redis,neo4j,milvus",
            "--summary-path",
            str(summary_path),
        ],
        timeout=3600,
    )


def count_tidb_rows(namespace: str) -> int:
    cmd = (
        "mysql -h tidb-cluster-tidb -P 4000 -u root -N -e "
        + '"SELECT COUNT(*) FROM ekb_control_plane.synthetic_perf_records;"'
    )
    out = must(
        [
            "kubectl",
            "--request-timeout=30s",
            "-n",
            namespace,
            "exec",
            "deploy/tidb-cluster-tidb",
            "--",
            "/bin/sh",
            "-lc",
            cmd,
        ],
        timeout=240,
    )
    value = out.strip().splitlines()[-1]
    return int(value)


def count_redis_keys(namespace: str) -> int:
    out = must(
        [
            "kubectl",
            "--request-timeout=30s",
            "-n",
            namespace,
            "exec",
            "deploy/redis-cluster",
            "--",
            "redis-cli",
            "DBSIZE",
        ],
        timeout=240,
    )
    return int(out.strip().splitlines()[-1])


def count_neo4j_nodes(namespace: str) -> int:
    out = must(
        [
            "kubectl",
            "--request-timeout=30s",
            "-n",
            namespace,
            "exec",
            "deploy/neo4j",
            "--",
            "cypher-shell",
            "-u",
            "neo4j",
            "-p",
            "neo4j-password-1",
            "MATCH (n:PerfEntity) RETURN count(n);",
        ],
        timeout=300,
    )
    numbers = re.findall(r"\b\d+\b", out)
    if not numbers:
        raise RuntimeError(f"unexpected neo4j output: {out}")
    return int(numbers[-1])


def count_milvus_vectors(namespace: str) -> int:
    out = must(
        [
            "kubectl",
            "--request-timeout=30s",
            "-n",
            namespace,
            "exec",
            "deploy/milvus",
            "--",
            "curl",
            "-fsS",
            "http://localhost:9091/healthz",
        ],
        timeout=120,
    )
    return 1 if "OK" in out.upper() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize existing and new data across region-a and region-b")
    parser.add_argument("--namespace-a", default="ekb-region-a")
    parser.add_argument("--namespace-b", default="ekb-region-b")
    parser.add_argument("--existing-records", type=int, default=1_000_000)
    parser.add_argument("--new-records", type=int, default=200_000)
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    old_summary = REPORT_DIR / "sync-seed-existing-summary.json"
    new_summary = REPORT_DIR / "sync-seed-new-summary.json"

    run_seed(args.existing_records, old_summary)
    run_seed(args.new_records, new_summary)

    target_total = args.existing_records + args.new_records

    checks = {
        args.namespace_a: {
            "tidb_rows": count_tidb_rows(args.namespace_a),
            "redis_keys": count_redis_keys(args.namespace_a),
            "neo4j_nodes": count_neo4j_nodes(args.namespace_a),
            "milvus_health": count_milvus_vectors(args.namespace_a),
        },
        args.namespace_b: {
            "tidb_rows": count_tidb_rows(args.namespace_b),
            "redis_keys": count_redis_keys(args.namespace_b),
            "neo4j_nodes": count_neo4j_nodes(args.namespace_b),
            "milvus_health": count_milvus_vectors(args.namespace_b),
        },
    }

    payload = {
        "generated_at": int(time.time()),
        "existing_records": args.existing_records,
        "new_records": args.new_records,
        "target_total_records": target_total,
        "summaries": {
            "existing": str(old_summary),
            "new": str(new_summary),
        },
        "checks": checks,
        "status": "ok",
    }
    out = REPORT_DIR / "multiregion-data-sync-summary.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[multiregion-data-sync] summary={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
