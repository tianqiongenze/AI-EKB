from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable

NS = "ekb-control-plane"


def run_cmd(command: list[str]) -> str:
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def run_cmd_allow_exists(command: list[str]) -> str:
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode == 0:
        return proc.stdout
    combined = f"{proc.stdout}\n{proc.stderr}"
    already_exists_markers = [
        "already exists",
        "Tenant already exist",
        "Namespace already exists",
        "This topic already exists",
    ]
    if any(marker in combined for marker in already_exists_markers):
        return proc.stdout
    raise RuntimeError(f"command failed: {' '.join(command)}\n{proc.stdout}\n{proc.stderr}")


def ensure_pod_ready(label: str) -> None:
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "wait",
        "--for=condition=ready",
        "pod",
        "-l",
        label,
        "--timeout=600s",
    ])


def create_pulsar_topics(topics: Iterable[str]) -> None:
    pods = run_cmd(["kubectl", "-n", NS, "get", "pods", "-l", "app=pulsar-broker", "-o", "json"])
    payload = json.loads(pods)
    items = payload.get("items", [])
    if not items:
        raise RuntimeError("no pulsar broker pod found")
    pod_name = items[0]["metadata"]["name"]
    run_cmd_allow_exists(
        [
            "kubectl",
            "-n",
            NS,
            "exec",
            pod_name,
            "--",
            "/pulsar/bin/pulsar-admin",
            "tenants",
            "create",
            "group",
            "--allowed-clusters",
            "standalone",
        ]
    )
    run_cmd_allow_exists(
        [
            "kubectl",
            "-n",
            NS,
            "exec",
            pod_name,
            "--",
            "/pulsar/bin/pulsar-admin",
            "namespaces",
            "create",
            "group/a2a",
        ]
    )
    run_cmd_allow_exists(
        [
            "kubectl",
            "-n",
            NS,
            "exec",
            pod_name,
            "--",
            "/pulsar/bin/pulsar-admin",
            "namespaces",
            "create",
            "group/control",
        ]
    )

    for topic in topics:
        run_cmd_allow_exists(
            [
                "kubectl",
                "-n",
                NS,
                "exec",
                pod_name,
                "--",
                "/pulsar/bin/pulsar-admin",
                "topics",
                "create",
                topic,
            ]
        )


def run() -> int:
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "rollout",
        "status",
        "deployment/tidb-cluster-tidb",
        "--timeout=600s",
    ])
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "rollout",
        "status",
        "deployment/pulsar-broker",
        "--timeout=600s",
    ])
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "rollout",
        "status",
        "deployment/redis-cluster",
        "--timeout=600s",
    ])
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "rollout",
        "status",
        "deployment/neo4j",
        "--timeout=600s",
    ])
    run_cmd([
        "kubectl",
        "-n",
        NS,
        "rollout",
        "status",
        "deployment/milvus",
        "--timeout=600s",
    ])

    ensure_pod_ready("app=tidb-cluster-tidb")
    ensure_pod_ready("app=pulsar-broker")
    ensure_pod_ready("app=redis-cluster")
    ensure_pod_ready("app=neo4j")
    ensure_pod_ready("app=milvus")

    create_pulsar_topics(
        [
            "persistent://group/a2a/default",
            "persistent://group/control/datalake-table-registered",
            "persistent://group/control/flink-pipeline-registered",
        ]
    )

    print("[k8s-stack-verify] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(run())
