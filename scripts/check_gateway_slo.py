from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K6_SCRIPT = ROOT / "perf" / "k6" / "load-test.js"


def _extract_threshold(pattern: str, content: str) -> int:
    match = re.search(pattern, content)
    if not match:
        raise ValueError(f"threshold pattern not found: {pattern}")
    return int(match.group(1))


def _extract_latency_thresholds(metric_names: list[str], content: str) -> tuple[int, int]:
    for metric_name in metric_names:
        pattern = rf"[\"']?{re.escape(metric_name)}[\"']?\s*:\s*\[([^\]]*)\]"
        match = re.search(pattern, content)
        if not match:
            continue
        percentiles = dict(re.findall(r"p\((\d+)\)<(\d+)", match.group(1)))
        if "95" in percentiles and "99" in percentiles:
            return int(percentiles["95"]), int(percentiles["99"])
    raise ValueError(f"threshold pattern not found for metrics: {', '.join(metric_names)}")


def run() -> int:
    content = K6_SCRIPT.read_text(encoding="utf-8")

    gateway_p95, gateway_p99 = _extract_latency_thresholds(
        ["gateway.latency", "gateway_latency"],
        content,
    )

    max_p95 = int(os.getenv("EKB_GATEWAY_SLO_MAX_P95_MS", "250"))
    max_p99 = int(os.getenv("EKB_GATEWAY_SLO_MAX_P99_MS", "500"))

    violations: list[str] = []
    if gateway_p95 > max_p95:
        violations.append(f"gateway p95 threshold too loose: {gateway_p95}ms > {max_p95}ms")
    if gateway_p99 > max_p99:
        violations.append(f"gateway p99 threshold too loose: {gateway_p99}ms > {max_p99}ms")

    if violations:
        print("[gateway-slo-gate] FAILED")
        for violation in violations:
            print(f"- {violation}")
        return 1

    print("[gateway-slo-gate] PASS")
    print(f"- gateway p95 threshold: {gateway_p95}ms")
    print(f"- gateway p99 threshold: {gateway_p99}ms")
    print(f"- policy max p95: {max_p95}ms")
    print(f"- policy max p99: {max_p99}ms")
    return 0


if __name__ == "__main__":
    sys.exit(run())
