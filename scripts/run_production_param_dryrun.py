from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "perf" / "reports"


def exec_cmd(command: list[str], timeout: int = 300) -> dict:
    proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "command": " ".join(command),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production parameterized dry-run suite")
    parser.add_argument("--namespace", default="ekb-control-plane")
    parser.add_argument("--flink-image", default="ekb-mirror/yadea-ekb-flink-session:local")
    parser.add_argument("--aws-access-key-id", default="dryrun-ak")
    parser.add_argument("--aws-secret-access-key", default="dryrun-sk")
    args = parser.parse_args()

    commands = [
        ["helm", "lint", str(ROOT / "infra/helm/ekb-control-plane")],
        ["helm", "lint", str(ROOT / "infra/helm/ekb-flink-jobs")],
        [
            "helm",
            "template",
            "ekb-control-plane",
            str(ROOT / "infra/helm/ekb-control-plane"),
            "--namespace",
            args.namespace,
            "--create-namespace",
        ],
        [
            "helm",
            "template",
            "ekb-flink-jobs",
            str(ROOT / "infra/helm/ekb-flink-jobs"),
            "--namespace",
            args.namespace,
            "--set",
            f"sessionCluster.image={args.flink_image}",
            "--set",
            f"credentials.awsAccessKeyId={args.aws_access_key_id}",
            "--set",
            f"credentials.awsSecretAccessKey={args.aws_secret_access_key}",
        ],
        ["kubectl", "--request-timeout=30s", "apply", "-f", str(ROOT / "infra/k8s/base/namespace.yaml"), "--dry-run=client"],
        ["kubectl", "--request-timeout=30s", "apply", "-f", str(ROOT / "infra/k8s/base/configmap.yaml"), "--dry-run=client"],
        ["kubectl", "--request-timeout=30s", "apply", "-f", str(ROOT / "infra/k8s/base/deployment-ekb-control-plane.yaml"), "--dry-run=client"],
        ["kubectl", "--request-timeout=30s", "apply", "-f", str(ROOT / "infra/k8s/base/deployment-go-gateway.yaml"), "--dry-run=client"],
        [sys.executable, str(ROOT / "scripts/check_contract_consistency.py")],
        [sys.executable, str(ROOT / "scripts/check_flink_runtime_preflight_contract.py")],
        [sys.executable, str(ROOT / "scripts/check_replay_e2e_slo.py")],
        [sys.executable, str(ROOT / "scripts/check_gateway_slo.py")],
        [sys.executable, str(ROOT / "scripts/check_gateway_perf_report.py")],
        [sys.executable, str(ROOT / "scripts/check_forbidden_artifacts.py")],
        [sys.executable, str(ROOT / "scripts/release_protect_artifacts.py"), "--mode", "verify"],
    ]

    results = [exec_cmd(cmd, timeout=600) for cmd in commands]
    status = "ok" if all(item["returncode"] == 0 for item in results) else "degraded"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / "production-param-dryrun-summary.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": int(time.time()),
                "namespace": args.namespace,
                "status": status,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[production-param-dryrun] summary={out} status={status}")
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
