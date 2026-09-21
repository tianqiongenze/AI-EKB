from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_TRAFFIC_DIR = ROOT / "infra" / "k8s" / "production-pack" / "global-traffic"
REGION_A_VALUES = (
    ROOT / "infra" / "k8s" / "production-pack" / "multicluster" / "regions" / "region-a" / "control-plane-values.yaml"
)
REGION_B_VALUES = (
    ROOT / "infra" / "k8s" / "production-pack" / "multicluster" / "regions" / "region-b" / "control-plane-values.yaml"
)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy production multi-cluster global traffic pack")
    parser.add_argument("--namespace", default="ekb-control-plane")
    parser.add_argument("--cluster-a-context", default="kind-ekb-region-a")
    parser.add_argument("--cluster-b-context", default="kind-ekb-region-b")
    parser.add_argument("--release", default="ekb-control-plane")
    args = parser.parse_args()

    run(
        [
            "helm",
            "upgrade",
            "--install",
            args.release,
            str(ROOT / "infra" / "helm" / "ekb-control-plane"),
            "--kube-context",
            args.cluster_a_context,
            "--namespace",
            args.namespace,
            "--create-namespace",
            "-f",
            str(REGION_A_VALUES),
        ]
    )
    run(
        [
            "helm",
            "upgrade",
            "--install",
            args.release,
            str(ROOT / "infra" / "helm" / "ekb-control-plane"),
            "--kube-context",
            args.cluster_b_context,
            "--namespace",
            args.namespace,
            "--create-namespace",
            "-f",
            str(REGION_B_VALUES),
        ]
    )

    for manifest in [
        "gatewayclass.yaml",
        "http-route-weighted.yaml",
        "health-policy.yaml",
        "global-dns-record.yaml",
    ]:
        run(
            [
                "kubectl",
                "--context",
                args.cluster_a_context,
                "apply",
                "-f",
                str(GLOBAL_TRAFFIC_DIR / manifest),
            ]
        )

    print("[production-pack] multicluster + global traffic deployment completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
