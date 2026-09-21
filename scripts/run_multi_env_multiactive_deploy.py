from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "perf" / "reports"


def run(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def must(command: list[str], timeout: int = 900) -> None:
    proc = run(command, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )


def wait_deploy(ns: str, deploy: str, timeout_seconds: int = 600) -> None:
    must(["kubectl", "--request-timeout=30s", "-n", ns, "rollout", "status", f"deployment/{deploy}", f"--timeout={timeout_seconds}s"], timeout=timeout_seconds + 60)


def apply_env_overlay(env: str) -> None:
    base_resources = [
        ROOT / "infra/k8s/base/namespace.yaml",
        ROOT / "infra/k8s/base/configmap.yaml",
        ROOT / "infra/k8s/base/deployment-ekb-control-plane.yaml",
        ROOT / "infra/k8s/base/deployment-go-gateway.yaml",
        ROOT / "infra/k8s/base/service.yaml",
        ROOT / "infra/k8s/base/service-go-gateway.yaml",
        ROOT / "infra/k8s/base/hpa.yaml",
        ROOT / "infra/k8s/base/hpa-go-gateway.yaml",
        ROOT / "infra/k8s/base/pdb.yaml",
        ROOT / "infra/k8s/base/pdb-go-gateway.yaml",
        ROOT / "infra/k8s/base/networkpolicy.yaml",
        ROOT / "infra/k8s/base/networkpolicy-go-gateway.yaml",
    ]

    for resource in base_resources:
        must(["kubectl", "--request-timeout=30s", "apply", "-f", str(resource)])

    if env == "dev":
        return
    elif env in {"staging", "prod"}:
        if env == "staging":
            must(["kubectl", "--request-timeout=30s", "-n", "ekb-control-plane", "scale", "deployment/ekb-control-plane", "--replicas=2"])
            must(["kubectl", "--request-timeout=30s", "-n", "ekb-control-plane", "scale", "deployment/ekb-go-gateway", "--replicas=2"])
        else:
            must(["kubectl", "--request-timeout=30s", "-n", "ekb-control-plane", "scale", "deployment/ekb-control-plane", "--replicas=8"])
            must(["kubectl", "--request-timeout=30s", "-n", "ekb-control-plane", "scale", "deployment/ekb-go-gateway", "--replicas=8"])
    else:
        raise RuntimeError(f"unsupported environment: {env}")


def ensure_env_namespaces(env: str) -> list[str]:
    namespaces = [f"ekb-{env}-region-a", f"ekb-{env}-region-b"]
    for ns in namespaces:
        run(["kubectl", "create", "ns", ns], timeout=60)
    return namespaces


def deploy_multiregion_for_env(env: str, replicas: int, timeout_seconds: int) -> None:
    ns_prefix = f"ekb-{env}"
    must(
        [
            sys.executable,
            str(ROOT / "scripts/deploy_multiregion_active_active.py"),
            "--cluster-name",
            "ekb-multiregion",
            "--region-a",
            "cn-north-1",
            "--region-b",
            "eu-central-1",
            "--namespace-prefix",
            ns_prefix,
            "--replicas-per-deployment",
            str(replicas),
            "--timeout-seconds",
            str(timeout_seconds),
        ],
        timeout=timeout_seconds + 600,
    )


def downscale_namespace(namespace: str) -> None:
    proc = run(["kubectl", "--request-timeout=30s", "-n", namespace, "get", "deploy", "-o", "jsonpath={range .items[*]}{.metadata.name}{'\n'}{end}"])
    if proc.returncode != 0:
        return
    names = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    for name in names:
        run(["kubectl", "--request-timeout=30s", "-n", namespace, "scale", f"deployment/{name}", "--replicas=0"], timeout=120)


def patch_namespace_config(namespace: str, env: str) -> None:
    proc = run(["kubectl", "--request-timeout=30s", "-n", namespace, "get", "configmap", "ekb-control-plane-config", "-o", "yaml"])
    if proc.returncode != 0:
        return
    doc = yaml.safe_load(proc.stdout)
    data = doc.setdefault("data", {})
    data["ENV"] = env
    if namespace.endswith("region-b"):
        data["DEFAULT_REGION"] = "eu-central-1"
    else:
        data["DEFAULT_REGION"] = "cn-north-1"
    payload = yaml.safe_dump(doc, sort_keys=False)
    apply_proc = subprocess.run(
        ["kubectl", "--request-timeout=30s", "apply", "-f", "-"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if apply_proc.returncode != 0:
        raise RuntimeError(
            f"failed patching configmap for {namespace}\nSTDOUT:\n{apply_proc.stdout}\nSTDERR:\n{apply_proc.stderr}"
        )


def verify_env(env: str) -> dict:
    namespaces = [f"ekb-{env}-region-a", f"ekb-{env}-region-b"]
    required = [
        "ekb-control-plane",
        "ekb-go-gateway",
        "tidb-cluster-tidb",
        "redis-cluster",
        "neo4j",
        "milvus",
        "pulsar-broker",
    ]

    status = {"environment": env, "namespaces": []}
    for ns in namespaces:
        ns_entry = {"namespace": ns, "deployments": []}
        for deploy in required:
            proc = run(["kubectl", "--request-timeout=30s", "-n", ns, "get", "deploy", deploy, "-o", "jsonpath={.status.readyReplicas}/{.status.replicas}"])
            value = proc.stdout.strip() if proc.returncode == 0 else "0/0"
            ns_entry["deployments"].append({"name": deploy, "ready": value})
        status["namespaces"].append(ns_entry)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy multi-env multi-active stack")
    parser.add_argument("--environments", default="dev,staging,prod")
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    envs = [item.strip() for item in args.environments.split(",") if item.strip()]
    results = []

    for idx, env in enumerate(envs):
        if idx > 0:
            for prev in envs[:idx]:
                downscale_namespace(f"ekb-{prev}-region-a")
                downscale_namespace(f"ekb-{prev}-region-b")
        apply_env_overlay(env)
        ensure_env_namespaces(env)
        deploy_multiregion_for_env(env, args.replicas, args.timeout_seconds)
        patch_namespace_config(f"ekb-{env}-region-a", env)
        patch_namespace_config(f"ekb-{env}-region-b", env)
        results.append(verify_env(env))
        time.sleep(2)

    payload = {
        "generated_at": int(time.time()),
        "environments": envs,
        "results": results,
        "status": "ok",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "multi-env-multiactive-summary.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[multi-env-multiactive] summary={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
