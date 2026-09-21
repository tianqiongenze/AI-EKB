from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "perf" / "reports" / "gateway-latest-summary.json"


def run() -> int:
    if not REPORT_PATH.exists():
        print(f"[gateway-perf-report] FAILED: report missing: {REPORT_PATH}")
        return 1

    payload = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    required = {"generated_at", "gateway_latency_p95_ms", "gateway_latency_p99_ms", "http_req_failed_rate"}
    missing = [k for k in sorted(required) if k not in payload]
    if missing:
        print("[gateway-perf-report] FAILED: missing keys")
        for key in missing:
            print(f"- {key}")
        return 1

    max_p95 = float(os.getenv("EKB_GATEWAY_SLO_MAX_P95_MS", "250"))
    max_p99 = float(os.getenv("EKB_GATEWAY_SLO_MAX_P99_MS", "500"))
    max_fail = float(os.getenv("EKB_GATEWAY_SLO_MAX_FAIL_RATE", "0.002"))

    p95 = float(payload["gateway_latency_p95_ms"])
    p99 = float(payload["gateway_latency_p99_ms"])
    fail_rate = float(payload["http_req_failed_rate"])

    violations: list[str] = []
    if p95 > max_p95:
        violations.append(f"p95 too high: {p95}ms > {max_p95}ms")
    if p99 > max_p99:
        violations.append(f"p99 too high: {p99}ms > {max_p99}ms")
    if fail_rate > max_fail:
        violations.append(f"error rate too high: {fail_rate} > {max_fail}")

    if violations:
        print("[gateway-perf-report] FAILED")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("[gateway-perf-report] PASS")
    print(f"- generated_at: {payload['generated_at']}")
    print(f"- gateway_latency_p95_ms: {p95}")
    print(f"- gateway_latency_p99_ms: {p99}")
    print(f"- http_req_failed_rate: {fail_rate}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
