from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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

        if command and command[0] == "kubectl" and attempt < retries - 1 and _is_transient_kubectl_error(proc):
            time.sleep(min(2 + attempt, 12))
            continue

        if check:
            raise subprocess.CalledProcessError(proc.returncode, command, output=proc.stdout, stderr=proc.stderr)
        return proc

    assert last is not None
    if check:
        raise subprocess.CalledProcessError(last.returncode, command, output=last.stdout, stderr=last.stderr)
    return last


def kubectl_json(args: list[str]) -> dict:
    proc = run_cmd(["kubectl", *args, "-o", "json"])
    return json.loads(proc.stdout)


def get_service_nodeport(namespace: str, name: str) -> int:
    payload = kubectl_json(["-n", namespace, "get", "svc", name])
    for port in payload.get("spec", {}).get("ports", []):
        if int(port.get("port", 0)) == 80 and "nodePort" in port:
            return int(port["nodePort"])
    raise RuntimeError(f"nodePort not found for {namespace}/{name}")


def ensure_nodeport(namespace: str, name: str) -> None:
    patch = '{"spec":{"type":"NodePort"}}'
    run_cmd(["kubectl", "-n", namespace, "patch", "svc", name, "-p", patch])


def wait_rollout(namespace: str, deploy: str, timeout_seconds: int) -> None:
    run_cmd(
        [
            "kubectl",
            "-n",
            namespace,
            "rollout",
            "status",
            f"deployment/{deploy}",
            f"--timeout={timeout_seconds}s",
        ]
    )


def run_k6(base_url: str, summary_path: Path, duration: str, vus: int) -> dict:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
import http from 'k6/http';
import {{ check, sleep }} from 'k6';
export const options = {{ vus: {vus}, duration: '{duration}' }};
export default function () {{
  const res = http.get('{base_url}/healthz');
  check(res, {{ 'status 200': (r) => r.status === 200 }});
  sleep(0.1);
}}
""".strip()

    cmd = [
        "k6",
        "run",
        "--summary-export",
        str(summary_path),
        "-",
    ]
    proc = subprocess.run(cmd, input=script, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"k6 failed for {base_url}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multiregion failover + load test")
    parser.add_argument("--namespace-a", default="ekb-region-a")
    parser.add_argument("--namespace-b", default="ekb-region-b")
    parser.add_argument("--duration", default="90s")
    parser.add_argument("--vus", type=int, default=200)
    parser.add_argument("--rollout-timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    ensure_nodeport(args.namespace_a, "ekb-go-gateway")
    ensure_nodeport(args.namespace_b, "ekb-go-gateway")
    port_a = get_service_nodeport(args.namespace_a, "ekb-go-gateway")
    port_b = get_service_nodeport(args.namespace_b, "ekb-go-gateway")

    base_a = f"http://127.0.0.1:{port_a}"
    base_b = f"http://127.0.0.1:{port_b}"

    pre_a = run_k6(base_a, ROOT / "perf/reports/multiregion-region-a-pre.json", args.duration, args.vus)
    pre_b = run_k6(base_b, ROOT / "perf/reports/multiregion-region-b-pre.json", args.duration, args.vus)

    run_cmd(["kubectl", "-n", args.namespace_a, "scale", "deployment/ekb-go-gateway", "--replicas=0"])
    wait_rollout(args.namespace_a, "ekb-go-gateway", args.rollout_timeout_seconds)

    failover_b = run_k6(
        base_b,
        ROOT / "perf/reports/multiregion-region-b-failover.json",
        args.duration,
        args.vus,
    )

    run_cmd(["kubectl", "-n", args.namespace_a, "scale", "deployment/ekb-go-gateway", "--replicas=2"])
    wait_rollout(args.namespace_a, "ekb-go-gateway", args.rollout_timeout_seconds)

    post_a = run_k6(base_a, ROOT / "perf/reports/multiregion-region-a-post.json", args.duration, args.vus)

    def metric(data: dict, name: str, key: str) -> float:
        return float(data.get("metrics", {}).get(name, {}).get(key, 0.0))

    report = {
        "generated_at": int(time.time()),
        "region_a": {
            "base_url": base_a,
            "pre": {
                "http_req_failed_rate": metric(pre_a, "http_req_failed", "rate"),
                "p95_ms": metric(pre_a, "http_req_duration", "p(95)"),
            },
            "post": {
                "http_req_failed_rate": metric(post_a, "http_req_failed", "rate"),
                "p95_ms": metric(post_a, "http_req_duration", "p(95)"),
            },
        },
        "region_b": {
            "base_url": base_b,
            "pre": {
                "http_req_failed_rate": metric(pre_b, "http_req_failed", "rate"),
                "p95_ms": metric(pre_b, "http_req_duration", "p(95)"),
            },
            "failover": {
                "http_req_failed_rate": metric(failover_b, "http_req_failed", "rate"),
                "p95_ms": metric(failover_b, "http_req_duration", "p(95)"),
            },
        },
        "status": "ok",
    }

    out = ROOT / "perf/reports/multiregion-failover-load-summary.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[multiregion-failover-load] PASS summary={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
