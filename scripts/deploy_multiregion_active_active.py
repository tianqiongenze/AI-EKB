from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTROL_PLANE_IMAGE = "yadea-ekb:0.2.0"
GO_GATEWAY_IMAGE = "yadea-ekb-go-gateway:0.2.0"
DEP_FILES = [
    ROOT / "infra/k8s/deps/pulsar-standalone.yaml",
    ROOT / "infra/k8s/deps/redis.yaml",
    ROOT / "infra/k8s/deps/neo4j.yaml",
    ROOT / "infra/k8s/deps/milvus.yaml",
    ROOT / "infra/k8s/deps/tidb-lite.yaml",
]
BASE_FILES = [
    ROOT / "infra/k8s/base/configmap.yaml",
    ROOT / "infra/k8s/base/service.yaml",
    ROOT / "infra/k8s/base/service-go-gateway.yaml",
    ROOT / "infra/k8s/base/deployment-ekb-control-plane.yaml",
    ROOT / "infra/k8s/base/deployment-go-gateway.yaml",
    ROOT / "infra/k8s/base/hpa.yaml",
    ROOT / "infra/k8s/base/hpa-go-gateway.yaml",
    ROOT / "infra/k8s/base/pdb.yaml",
    ROOT / "infra/k8s/base/pdb-go-gateway.yaml",
    ROOT / "infra/k8s/base/networkpolicy.yaml",
    ROOT / "infra/k8s/base/networkpolicy-go-gateway.yaml",
]
NAMESPACED_KINDS = {
    "Deployment",
    "Service",
    "ConfigMap",
    "Secret",
    "HorizontalPodAutoscaler",
    "PodDisruptionBudget",
    "NetworkPolicy",
}


@dataclass
class RegionConfig:
    name: str
    namespace: str


def _is_transient_kubectl_error(proc: subprocess.CompletedProcess[str]) -> bool:
    text = f"{proc.stdout}\n{proc.stderr}"
    markers = [
        "TLS handshake timeout",
        "context deadline exceeded",
        "Timeout: request did not complete",
        "the server is currently unable to handle the request",
        "client connection lost",
        "connection reset by peer",
        "i/o timeout",
        "EOF",
    ]
    return any(marker in text for marker in markers)


def run_cmd(command: list[str], *, check: bool = True, retries: int = 12) -> subprocess.CompletedProcess[str]:
    if command and command[0] == "kubectl" and not any(arg.startswith("--request-timeout=") for arg in command):
        command = ["kubectl", "--request-timeout=20s", *command[1:]]

    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(retries):
        proc = subprocess.run(command, text=True, capture_output=True, check=False)
        last = proc
        if proc.returncode == 0:
            return proc
        is_kubectl = bool(command) and command[0] == "kubectl"
        if is_kubectl and attempt < retries - 1 and _is_transient_kubectl_error(proc):
            time.sleep(min(2 + attempt, 12))
            continue
        if check:
            raise subprocess.CalledProcessError(proc.returncode, command, output=proc.stdout, stderr=proc.stderr)
        return proc

    assert last is not None
    if check:
        raise subprocess.CalledProcessError(last.returncode, command, output=last.stdout, stderr=last.stderr)
    return last


def ensure_cmd(name: str) -> None:
    proc = run_cmd(["bash", "-lc", f"command -v {name}"], check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"missing required command: {name}")


def ensure_runtime_images(cluster_name: str) -> None:
    run_cmd(["docker", "image", "inspect", CONTROL_PLANE_IMAGE], check=False, retries=1)
    if run_cmd(["docker", "image", "inspect", CONTROL_PLANE_IMAGE], check=False, retries=1).returncode != 0:
        run_cmd(["docker", "build", "-t", CONTROL_PLANE_IMAGE, str(ROOT)], retries=1)

    if run_cmd(["docker", "image", "inspect", GO_GATEWAY_IMAGE], check=False, retries=1).returncode != 0:
        run_cmd(
            [
                "docker",
                "build",
                "-t",
                GO_GATEWAY_IMAGE,
                "-f",
                str(ROOT / "services/go-gateway/Dockerfile"),
                str(ROOT),
            ],
            retries=1,
        )

    run_cmd(["kind", "load", "docker-image", CONTROL_PLANE_IMAGE, "--name", cluster_name], retries=1)
    run_cmd(["kind", "load", "docker-image", GO_GATEWAY_IMAGE, "--name", cluster_name], retries=1)


def ensure_kind_cluster(cluster_name: str) -> None:
    existing = run_cmd(["kind", "get", "clusters"], check=False)
    if existing.returncode == 0 and cluster_name in existing.stdout.split():
        run_cmd(["kubectl", "config", "use-context", f"kind-{cluster_name}"])
        return
    run_cmd(["kind", "create", "cluster", "--name", cluster_name])
    run_cmd(["kubectl", "config", "use-context", f"kind-{cluster_name}"])


def recreate_kind_cluster(cluster_name: str) -> None:
    run_cmd(["kind", "delete", "cluster", "--name", cluster_name], check=False, retries=1)
    run_cmd(["kind", "create", "cluster", "--name", cluster_name])
    run_cmd(["kubectl", "config", "use-context", f"kind-{cluster_name}"])


def wait_for_apiserver_ready(max_attempts: int = 40) -> None:
    for attempt in range(max_attempts):
        proc = run_cmd(["kubectl", "get", "--raw=/readyz"], check=False, retries=1)
        if proc.returncode == 0 and "ok" in proc.stdout:
            return
        time.sleep(min(2 + attempt, 10))
    raise RuntimeError("kubernetes apiserver did not become ready in time")


def load_docs(path: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if isinstance(doc, dict):
            docs.append(doc)
    return docs


def transform_doc(doc: dict[str, Any], region: RegionConfig, replicas: int) -> dict[str, Any]:
    kind = str(doc.get("kind", ""))
    metadata = doc.setdefault("metadata", {})
    labels = metadata.setdefault("labels", {})
    labels["topology.ekb.yadea/region"] = region.name
    labels["app.kubernetes.io/managed-by"] = "multiregion-sim"

    if kind in NAMESPACED_KINDS:
        metadata["namespace"] = region.namespace

    if kind == "ConfigMap" and metadata.get("name") == "ekb-control-plane-config":
        data = doc.setdefault("data", {})
        data["DEFAULT_REGION"] = region.name

    if kind == "Deployment":
        spec = doc.setdefault("spec", {})
        spec["replicas"] = max(1, replicas)

        tpl_meta = spec.setdefault("template", {}).setdefault("metadata", {})
        tpl_labels = tpl_meta.setdefault("labels", {})
        tpl_labels["topology.ekb.yadea/region"] = region.name

        if metadata.get("name") == "ekb-go-gateway":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                containers[0]["image"] = GO_GATEWAY_IMAGE
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "100m", "memory": "128Mi"}
                resources["limits"] = {"cpu": "500m", "memory": "512Mi"}

            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                env = containers[0].setdefault("env", [])
                sanitized = []
                for item in env:
                    if item.get("name") in {"EKB_GATEWAY_AUTH_TOKEN", "EKB_GATEWAY_PULSAR_REQUIRED"}:
                        continue
                    sanitized.append(item)
                sanitized.append({"name": "EKB_GATEWAY_AUTH_TOKEN", "value": ""})
                sanitized.append({"name": "EKB_GATEWAY_PULSAR_REQUIRED", "value": "false"})
                containers[0]["env"] = sanitized

        if metadata.get("name") == "ekb-control-plane":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                containers[0]["image"] = CONTROL_PLANE_IMAGE
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "100m", "memory": "256Mi"}
                resources["limits"] = {"cpu": "500m", "memory": "512Mi"}

        if metadata.get("name") == "redis-cluster":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "50m", "memory": "128Mi"}
                resources["limits"] = {"cpu": "250m", "memory": "256Mi"}

        if metadata.get("name") == "tidb-cluster-tidb":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "150m", "memory": "256Mi"}
                resources["limits"] = {"cpu": "600m", "memory": "768Mi"}

        if metadata.get("name") == "milvus":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "150m", "memory": "256Mi"}
                resources["limits"] = {"cpu": "600m", "memory": "768Mi"}

        if metadata.get("name") == "neo4j":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "100m", "memory": "384Mi"}
                resources["limits"] = {"cpu": "500m", "memory": "768Mi"}
                env = [item for item in containers[0].setdefault("env", []) if item.get("name") not in {
                    "NEO4J_server_memory_heap_initial__size",
                    "NEO4J_server_memory_heap_max__size",
                    "NEO4J_server_memory_pagecache_size",
                }]
                env.append({"name": "NEO4J_server_memory_heap_initial__size", "value": "256m"})
                env.append({"name": "NEO4J_server_memory_heap_max__size", "value": "256m"})
                env.append({"name": "NEO4J_server_memory_pagecache_size", "value": "128m"})
                containers[0]["env"] = env

        if metadata.get("name") == "pulsar-broker":
            containers = spec.setdefault("template", {}).setdefault("spec", {}).setdefault("containers", [])
            if containers:
                resources = containers[0].setdefault("resources", {})
                resources["requests"] = {"cpu": "150m", "memory": "384Mi"}
                resources["limits"] = {"cpu": "600m", "memory": "1024Mi"}
                env = [item for item in containers[0].setdefault("env", []) if item.get("name") != "PULSAR_MEM"]
                env.append({"name": "PULSAR_MEM", "value": "-Xms256m -Xmx256m -XX:MaxDirectMemorySize=256m"})
                containers[0]["env"] = env

    if kind == "HorizontalPodAutoscaler":
        spec = doc.setdefault("spec", {})
        spec["minReplicas"] = max(1, replicas)
        spec["maxReplicas"] = max(max(1, replicas), replicas * 2)

    return doc


def apply_docs(docs: list[dict[str, Any]]) -> None:
    payload = "\n---\n".join(yaml.safe_dump(doc, sort_keys=False) for doc in docs)
    proc: subprocess.CompletedProcess[str] | None = None
    for attempt in range(16):
        proc = subprocess.run(
            ["kubectl", "--request-timeout=20s", "apply", "--validate=false", "-f", "-"],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            break
        if attempt < 15 and _is_transient_kubectl_error(proc):
            time.sleep(min(2 + attempt, 12))
            continue
        break

    assert proc is not None
    if proc.returncode != 0:
        raise RuntimeError(f"kubectl apply failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


def ensure_namespace(region: RegionConfig) -> None:
    proc = run_cmd(["kubectl", "get", "namespace", region.namespace], check=False, retries=6)
    if proc.returncode == 0:
        run_cmd(
            [
                "kubectl",
                "label",
                "namespace",
                region.namespace,
                f"topology.ekb.yadea/region={region.name}",
                f"topology.kubernetes.io/region={region.name}",
                "--overwrite",
            ],
            retries=6,
        )
        return

    doc = {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": region.namespace,
            "labels": {
                "topology.ekb.yadea/region": region.name,
                "topology.kubernetes.io/region": region.name,
            },
        },
    }
    payload = yaml.safe_dump(doc, sort_keys=False)
    created = False
    for attempt in range(16):
        proc_create = subprocess.run(
            ["kubectl", "--request-timeout=20s", "create", "--validate=false", "-f", "-"],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc_create.returncode == 0:
            created = True
            break
        if "AlreadyExists" in f"{proc_create.stdout}\n{proc_create.stderr}":
            created = True
            break
        if attempt < 15 and _is_transient_kubectl_error(proc_create):
            time.sleep(min(2 + attempt, 12))
            continue
        raise RuntimeError(
            f"failed to create namespace {region.namespace}\nSTDOUT:\n{proc_create.stdout}\nSTDERR:\n{proc_create.stderr}"
        )

    if not created:
        raise RuntimeError(f"failed to create namespace {region.namespace}")


def wait_deploy(namespace: str, name: str, timeout_seconds: int) -> None:
    try:
        run_cmd(
            [
                "kubectl",
                "-n",
                namespace,
                "rollout",
                "status",
                f"deployment/{name}",
                f"--timeout={timeout_seconds}s",
            ]
        )
    except subprocess.CalledProcessError as exc:
        pods = run_cmd(
            ["kubectl", "-n", namespace, "get", "pods", "-o", "wide"],
            check=False,
            retries=4,
        )
        events = run_cmd(
            ["kubectl", "-n", namespace, "get", "events", "--sort-by=.lastTimestamp"],
            check=False,
            retries=4,
        )
        raise RuntimeError(
            f"rollout failed for deployment/{name} in {namespace}\n"
            f"STDOUT:\n{exc.stdout}\nSTDERR:\n{exc.stderr}\n"
            f"PODS:\n{pods.stdout}\nEVENTS:\n{events.stdout}"
        ) from exc


def create_pulsar_topics(namespace: str) -> None:
    pods = run_cmd(["kubectl", "-n", namespace, "get", "pods", "-l", "app=pulsar-broker", "-o", "json"])
    payload = json.loads(pods.stdout)
    items = payload.get("items", [])
    if not items:
        return
    pod_name = items[0]["metadata"]["name"]

    commands = [
        ["tenants", "create", "group", "--allowed-clusters", "standalone"],
        ["namespaces", "create", "group/a2a"],
        ["topics", "create", "persistent://group/a2a/default"],
    ]
    for cmd in commands:
        proc = run_cmd(
            ["kubectl", "-n", namespace, "exec", pod_name, "--", "/pulsar/bin/pulsar-admin", *cmd],
            check=False,
        )
        if proc.returncode != 0:
            text = f"{proc.stdout}\n{proc.stderr}"
            if "already exists" in text or "already exist" in text:
                continue
            raise RuntimeError(f"pulsar topic init failed in {namespace}: {' '.join(cmd)}\n{text}")


def deploy_region(region: RegionConfig, replicas: int, timeout_seconds: int) -> None:
    ensure_namespace(region)

    dep_docs: list[dict[str, Any]] = []
    for file in DEP_FILES + BASE_FILES:
        for doc in load_docs(file):
            dep_docs.append(transform_doc(doc, region, replicas))
    apply_docs(dep_docs)

    wait_deploy(region.namespace, "tidb-cluster-tidb", timeout_seconds)
    wait_deploy(region.namespace, "pulsar-broker", timeout_seconds)
    wait_deploy(region.namespace, "redis-cluster", timeout_seconds)
    wait_deploy(region.namespace, "neo4j", timeout_seconds)
    wait_deploy(region.namespace, "milvus", timeout_seconds)
    wait_deploy(region.namespace, "ekb-control-plane", timeout_seconds)
    wait_deploy(region.namespace, "ekb-go-gateway", timeout_seconds)

    create_pulsar_topics(region.namespace)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy 2-region active-active simulation on Kubernetes")
    parser.add_argument("--cluster-name", default="ekb-multiregion")
    parser.add_argument("--region-a", default="cn-north-1")
    parser.add_argument("--region-b", default="eu-central-1")
    parser.add_argument("--namespace-prefix", default="ekb")
    parser.add_argument("--replicas-per-deployment", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    ensure_cmd("kubectl")
    ensure_cmd("kind")
    ensure_cmd("docker")
    ensure_kind_cluster(args.cluster_name)
    try:
        wait_for_apiserver_ready()
    except RuntimeError:
        print("[multiregion-deploy] apiserver unhealthy, recreating kind cluster")
        recreate_kind_cluster(args.cluster_name)
        wait_for_apiserver_ready()

    ensure_runtime_images(args.cluster_name)

    regions = [
        RegionConfig(name=args.region_a, namespace=f"{args.namespace_prefix}-region-a"),
        RegionConfig(name=args.region_b, namespace=f"{args.namespace_prefix}-region-b"),
    ]

    started = time.time()
    for region in regions:
        print(f"[multiregion-deploy] deploying region={region.name} namespace={region.namespace}")
        deploy_region(region, args.replicas_per_deployment, args.timeout_seconds)

    summary = {
        "generated_at": int(time.time()),
        "cluster": args.cluster_name,
        "regions": [region.__dict__ for region in regions],
        "replicas_per_deployment": args.replicas_per_deployment,
        "seconds": round(time.time() - started, 3),
        "status": "ok",
    }
    out_path = ROOT / "perf" / "reports" / "multiregion-deploy-summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[multiregion-deploy] PASS summary={out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
