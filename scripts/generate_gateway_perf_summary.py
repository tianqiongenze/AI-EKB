from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOAD_SUMMARY_PATH = ROOT / "perf" / "reports" / "load-latest-summary.json"
GATEWAY_SUMMARY_PATH = ROOT / "perf" / "reports" / "gateway-latest-summary.json"


def _extract_metric(metrics: dict[str, object], key: str) -> dict[str, object]:
    value = metrics.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _to_float(value: object) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def run() -> int:
    if not LOAD_SUMMARY_PATH.exists():
        print(f"[gateway-summary] load report missing: {LOAD_SUMMARY_PATH}")
        return 1

    payload = json.loads(LOAD_SUMMARY_PATH.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}
    if not isinstance(metrics, dict):
        print("[gateway-summary] invalid metrics format")
        return 1

    gateway = _extract_metric(metrics, "gateway_latency")
    failed = _extract_metric(metrics, "http_req_failed")

    p95 = _to_float(gateway.get("p(95)", 0.0))
    p99 = _to_float(gateway.get("p(99)", 0.0))
    fail_rate = _to_float(failed.get("value", 0.0))

    summary = {
        "generated_at": int(time.time()),
        "gateway_latency_p95_ms": round(p95, 3),
        "gateway_latency_p99_ms": round(p99, 3),
        "http_req_failed_rate": round(fail_rate, 6),
        "source": "perf/reports/load-latest-summary.json",
    }

    GATEWAY_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[gateway-summary] generated")
    print(f"- output: {GATEWAY_SUMMARY_PATH}")
    print(f"- p95: {summary['gateway_latency_p95_ms']}")
    print(f"- p99: {summary['gateway_latency_p99_ms']}")
    print(f"- failed_rate: {summary['http_req_failed_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
