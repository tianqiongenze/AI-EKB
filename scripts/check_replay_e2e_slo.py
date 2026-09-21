from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K6_SCRIPT = ROOT / "perf" / "k6" / "replay-e2e-load-test.js"


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

    fail_rate_match = re.search(r"http_req_failed: \['rate<(0?\.\d+)'\]", content)
    if not fail_rate_match:
        raise ValueError("http_req_failed threshold not found")
    fail_rate = float(fail_rate_match.group(1))

    relay_p95, relay_p99 = _extract_latency_thresholds(["relay.latency", "relay_latency"], content)
    a2a_p95, a2a_p99 = _extract_latency_thresholds(["a2a.publish.latency", "a2a_publish_latency"], content)
    sub_p95, sub_p99 = _extract_latency_thresholds(["subagent.delegate.latency", "subagent_delegate_latency"], content)

    max_relay_p95 = int(os.getenv("EKB_REPLAY_SLO_MAX_RELAY_P95_MS", "350"))
    max_relay_p99 = int(os.getenv("EKB_REPLAY_SLO_MAX_RELAY_P99_MS", "700"))
    max_a2a_p95 = int(os.getenv("EKB_REPLAY_SLO_MAX_A2A_P95_MS", "180"))
    max_a2a_p99 = int(os.getenv("EKB_REPLAY_SLO_MAX_A2A_P99_MS", "350"))
    max_sub_p95 = int(os.getenv("EKB_REPLAY_SLO_MAX_SUB_P95_MS", "250"))
    max_sub_p99 = int(os.getenv("EKB_REPLAY_SLO_MAX_SUB_P99_MS", "500"))
    max_fail_rate = float(os.getenv("EKB_REPLAY_SLO_MAX_FAIL_RATE", "0.005"))

    violations: list[str] = []
    if relay_p95 > max_relay_p95:
        violations.append(f"relay p95 too loose: {relay_p95}ms > {max_relay_p95}ms")
    if relay_p99 > max_relay_p99:
        violations.append(f"relay p99 too loose: {relay_p99}ms > {max_relay_p99}ms")
    if a2a_p95 > max_a2a_p95:
        violations.append(f"a2a p95 too loose: {a2a_p95}ms > {max_a2a_p95}ms")
    if a2a_p99 > max_a2a_p99:
        violations.append(f"a2a p99 too loose: {a2a_p99}ms > {max_a2a_p99}ms")
    if sub_p95 > max_sub_p95:
        violations.append(f"subagent p95 too loose: {sub_p95}ms > {max_sub_p95}ms")
    if sub_p99 > max_sub_p99:
        violations.append(f"subagent p99 too loose: {sub_p99}ms > {max_sub_p99}ms")
    if fail_rate > max_fail_rate:
        violations.append(f"http_req_failed too loose: {fail_rate} > {max_fail_rate}")

    if violations:
        print("[replay-e2e-slo-gate] FAILED")
        for v in violations:
            print(f"- {v}")
        return 1

    print("[replay-e2e-slo-gate] PASS")
    print(f"- relay p95: {relay_p95}ms")
    print(f"- relay p99: {relay_p99}ms")
    print(f"- a2a publish p95: {a2a_p95}ms")
    print(f"- a2a publish p99: {a2a_p99}ms")
    print(f"- sub-agent delegate p95: {sub_p95}ms")
    print(f"- sub-agent delegate p99: {sub_p99}ms")
    print(f"- http_req_failed rate: {fail_rate}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
