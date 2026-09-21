from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "perf" / "reports" / "multi-env-multiactive-summary.json"


def run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)


def must(command: list[str], timeout: int = 300) -> str:
    proc = run(command, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def apply_yaml(doc: dict) -> None:
    payload = yaml.safe_dump(doc, sort_keys=False)
    proc = subprocess.run(
        ["kubectl", "--request-timeout=30s", "apply", "-f", "-"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"kubectl apply failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")


def load_doc(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid yaml doc: {path}")
    return data


def ensure_clean_ns(namespace: str) -> None:
    run(["kubectl", "--request-timeout=30s", "delete", "ns", namespace, "--ignore-not-found=true"], timeout=120)
    for _ in range(60):
        check = run(["kubectl", "--request-timeout=30s", "get", "ns", namespace], timeout=30)
        if check.returncode != 0:
            break
        time.sleep(2)
    must(["kubectl", "--request-timeout=30s", "create", "ns", namespace], timeout=60)


def deploy_env_region(env: str, region: str, namespace: str, replicas: int) -> dict:
    ensure_clean_ns(namespace)

    cfg = load_doc(ROOT / "infra/k8s/base/configmap.yaml")
    cfg.setdefault("metadata", {})["namespace"] = namespace
    data = cfg.setdefault("data", {})
    data["ENV"] = env
    data["DEFAULT_REGION"] = region
    data["EKB_TIDB_HOST"] = f"tidb-cluster-tidb.ekb-region-{'a' if region == 'cn-north-1' else 'b'}.svc.cluster.local"
    data["EKB_REDIS_URL"] = f"redis://redis-cluster.ekb-region-{'a' if region == 'cn-north-1' else 'b'}.svc.cluster.local:6379/0"
    data["EKB_NEO4J_URI"] = f"bolt://neo4j.ekb-region-{'a' if region == 'cn-north-1' else 'b'}.svc.cluster.local:7687"
    data["EKB_MILVUS_URI"] = f"http://milvus.ekb-region-{'a' if region == 'cn-north-1' else 'b'}.svc.cluster.local:19530"
    data["EKB_PULSAR_SERVICE_URL"] = f"pulsar://pulsar-broker.ekb-region-{'a' if region == 'cn-north-1' else 'b'}.svc.cluster.local:6650"
    apply_yaml(cfg)

    svc_cp = load_doc(ROOT / "infra/k8s/base/service.yaml")
    svc_cp.setdefault("metadata", {})["namespace"] = namespace
    apply_yaml(svc_cp)

    svc_gw = load_doc(ROOT / "infra/k8s/base/service-go-gateway.yaml")
    svc_gw.setdefault("metadata", {})["namespace"] = namespace
    apply_yaml(svc_gw)

    dep_cp = load_doc(ROOT / "infra/k8s/base/deployment-ekb-control-plane.yaml")
    dep_cp.setdefault("metadata", {})["namespace"] = namespace
    dep_cp.setdefault("spec", {})["replicas"] = replicas
    cp_container = dep_cp["spec"]["template"]["spec"]["containers"][0]
    cp_container["resources"] = {
        "requests": {"cpu": "10m", "memory": "64Mi"},
        "limits": {"cpu": "200m", "memory": "256Mi"},
    }
    apply_yaml(dep_cp)

    dep_gw = load_doc(ROOT / "infra/k8s/base/deployment-go-gateway.yaml")
    dep_gw.setdefault("metadata", {})["namespace"] = namespace
    dep_gw.setdefault("spec", {})["replicas"] = replicas
    gw_container = dep_gw["spec"]["template"]["spec"]["containers"][0]
    gw_container["resources"] = {
        "requests": {"cpu": "10m", "memory": "64Mi"},
        "limits": {"cpu": "150m", "memory": "256Mi"},
    }
    envs = [item for item in gw_container.get("env", []) if item.get("name") not in {"EKB_GATEWAY_AUTH_TOKEN", "EKB_GATEWAY_PULSAR_REQUIRED"}]
    envs.append({"name": "EKB_GATEWAY_AUTH_TOKEN", "value": ""})
    envs.append({"name": "EKB_GATEWAY_PULSAR_REQUIRED", "value": "false"})
    gw_container["env"] = envs
    apply_yaml(dep_gw)

    must([
        "kubectl",
        "--request-timeout=30s",
        "-n",
        namespace,
        "rollout",
        "status",
        "deployment/ekb-control-plane",
        "--timeout=600s",
    ], timeout=660)
    must([
        "kubectl",
        "--request-timeout=30s",
        "-n",
        namespace,
        "rollout",
        "status",
        "deployment/ekb-go-gateway",
        "--timeout=600s",
    ], timeout=660)

    return {
        "namespace": namespace,
        "control_plane": "ready",
        "gateway": "ready",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy lightweight multi-environment multi-active app planes")
    parser.add_argument("--environments", default="dev,staging,prod")
    parser.add_argument("--replicas", type=int, default=1)
    args = parser.parse_args()

    envs = [item.strip() for item in args.environments.split(",") if item.strip()]
    results: list[dict] = []
    for env in envs:
        results.append(
            {
                "environment": env,
                "regions": [
                    deploy_env_region(env, "cn-north-1", f"ekb-{env}-region-a", args.replicas),
                    deploy_env_region(env, "eu-central-1", f"ekb-{env}-region-b", args.replicas),
                ],
            }
        )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "generated_at": int(time.time()),
                "mode": "lightweight-app-plane-multiactive",
                "environments": envs,
                "results": results,
                "status": "ok",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[multi-env-multiactive-light] summary={REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
