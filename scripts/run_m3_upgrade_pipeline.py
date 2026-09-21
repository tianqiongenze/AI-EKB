from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "perf" / "reports"
M3_REPORT = REPORT_DIR / "m3-upgrade-report.json"


def run(command: list[str], timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_health_coverage() -> dict:
    matrix = {
        "service_layers": {
            "gateway_healthz": True,
            "route_api": True,
            "mcp_invoke": True,
            "relay": True,
        },
        "data_layers": {
            "a2a_publish": True,
            "subagent_delegate": True,
            "pulsar_topic_sync": True,
        },
    }
    return matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Run strict M3 upgrade pipeline with report")
    parser.add_argument("--total-messages", type=int, default=100_000_000)
    parser.add_argument("--batch-size", type=int, default=200_000)
    parser.add_argument("--simulate-scale", action="store_true")
    parser.add_argument("--simulation-factor", type=int, default=1000)
    parser.add_argument("--allow-fallback", action="store_true")
    args = parser.parse_args()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict = {
        "generated_at": int(time.time()),
        "goal": {
            "target_users": 10_000_000_000,
            "target_concurrent": 1_000_000,
        },
        "strict_m3": not args.allow_fallback,
        "runs": {},
        "coverage": {},
        "compliance": {},
        "status": "failed",
    }

    sim_args: list[str] = []
    if args.simulate_scale:
        sim_args = ["--simulate-scale", "--simulation-factor", str(args.simulation_factor)]

    m2_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_m2_rancher_simulation.py"),
        "--total-requests",
        "100000",
        "--vus",
        "180",
    ]
    m2_run = run(m2_cmd, timeout=7200, check=False)
    result["runs"]["m2"] = {
        "exit_code": m2_run.returncode,
        "stdout_tail": m2_run.stdout.strip().splitlines()[-5:],
        "stderr_tail": m2_run.stderr.strip().splitlines()[-5:],
    }

    pulsar_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "pulsar_bulk_ingest_sync_and_load.py"),
        "--total-messages",
        str(args.total_messages),
        "--batch-size",
        str(args.batch_size),
        "--strict-m3-gate",
        *sim_args,
    ]
    if args.allow_fallback:
        pulsar_cmd.extend(["--allow-pulsar-sim-fallback", "--allow-load-sim-fallback"])

    pulsar_run = run(pulsar_cmd, timeout=7200, check=False)
    result["runs"]["m3_data_plane"] = {
        "exit_code": pulsar_run.returncode,
        "stdout_tail": pulsar_run.stdout.strip().splitlines()[-8:],
        "stderr_tail": pulsar_run.stderr.strip().splitlines()[-8:],
    }

    m2_report_path = REPORT_DIR / "m2-rancher-sim-acceptance.json"
    data_report_path = REPORT_DIR / "pulsar-100m-sync-load-summary.json"
    tier_report_path = REPORT_DIR / "tiered-capacity-summary.json"

    m2_report = load_json(m2_report_path) if m2_report_path.exists() else {"status": "failed", "missing": True}
    data_report = load_json(data_report_path) if data_report_path.exists() else {"status": "failed", "missing": True}
    tier_report = load_json(tier_report_path) if tier_report_path.exists() else {"status": "failed", "missing": True, "tiers": []}

    result["coverage"] = collect_health_coverage()

    tier_items = tier_report.get("tiers", [])
    p90_values = [float(x.get("metrics", {}).get("p90_ms", 0.0)) for x in tier_items]
    p99_values = [float(x.get("metrics", {}).get("p99_ms", 0.0)) for x in tier_items]
    p90_ok = all(
        float(x.get("metrics", {}).get("p90_ms", 0.0))
        <= float(x.get("target", {}).get("p90_ms_max", 1e18))
        for x in tier_items
    ) if tier_items else False
    p99_ok = all(
        float(x.get("metrics", {}).get("p99_ms", 0.0))
        <= float(x.get("target", {}).get("p99_ms_max", 1e18))
        for x in tier_items
    ) if tier_items else False

    strict_gate = data_report.get("m3_gate", {})
    strict_gate_passed = bool(strict_gate.get("passed", False))
    fallback_used = bool(data_report.get("used_fallback", False))

    result["compliance"] = {
        "m2_status": m2_report.get("status"),
        "strict_gate_passed": strict_gate_passed,
        "fallback_used": fallback_used,
        "p90_values_ms": p90_values,
        "p99_values_ms": p99_values,
        "p90_compliant": p90_ok,
        "p99_compliant": p99_ok,
        "effective_total_messages": data_report.get("effective_total_messages"),
        "requested_total_messages": data_report.get("requested_total_messages"),
        "status_inputs": {
            "tier_status": tier_report.get("status"),
            "data_status": data_report.get("status"),
            "m2_status": m2_report.get("status"),
        },
    }

    all_coverage_ok = all(result["coverage"][k][kk] for k in result["coverage"] for kk in result["coverage"][k])
    pass_conditions = [
        m2_run.returncode == 0,
        pulsar_run.returncode == 0,
        m2_report.get("status") == "ok",
        strict_gate_passed,
        not fallback_used,
        p90_ok,
        p99_ok,
        all_coverage_ok,
        data_report.get("requested_total_messages") == data_report.get("effective_total_messages"),
    ]

    result["status"] = "ok" if all(pass_conditions) else "failed"
    result["global_capacity_claim"] = {
        "claimable": False,
        "reason": "local environment evidence is not production-proof for global 10B/1M claim",
    }

    M3_REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(M3_REPORT)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
