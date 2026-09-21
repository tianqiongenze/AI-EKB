from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIERS_FILE = ROOT / "perf" / "tiered" / "tiers.yaml"
K6_SCRIPT = ROOT / "perf" / "k6" / "tiered-gateway-load.js"


FALLBACK_TIERS = [
    {
        "id": "tier-0-canary",
        "vus": 20,
        "duration": "2m",
        "failover": False,
        "target": {"error_rate_max": 0.002, "p90_ms_max": 180, "p95_ms_max": 250, "p99_ms_max": 500},
    },
    {
        "id": "tier-1-regional-baseline",
        "vus": 80,
        "duration": "8m",
        "failover": False,
        "target": {"error_rate_max": 0.003, "p90_ms_max": 260, "p95_ms_max": 350, "p99_ms_max": 800},
    },
    {
        "id": "tier-2-regional-peak",
        "vus": 200,
        "duration": "15m",
        "failover": False,
        "target": {"error_rate_max": 0.005, "p90_ms_max": 360, "p95_ms_max": 500, "p99_ms_max": 1200},
    },
    {
        "id": "tier-3-multiregion-failover",
        "vus": 300,
        "duration": "12m",
        "failover": True,
        "target": {"error_rate_max": 0.008, "p90_ms_max": 520, "p95_ms_max": 700, "p99_ms_max": 1600},
    },
    {
        "id": "tier-4-global-stress-sim",
        "vus": 600,
        "duration": "20m",
        "failover": True,
        "target": {"error_rate_max": 0.015, "p90_ms_max": 760, "p95_ms_max": 1000, "p99_ms_max": 2200},
    },
]


def parse_scalar(value: str):
    text = value.strip()
    if text == "":
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(ch in text for ch in [".", "e", "E"]):
            return float(text)
        return int(text)
    except ValueError:
        return text


def parse_tiers_yaml(text: str) -> list[dict]:
    tiers: list[dict] = []
    current: dict | None = None
    in_target = False

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if stripped == "tiers:":
            continue

        if stripped.startswith("- "):
            if current is not None:
                if "target" not in current or not isinstance(current["target"], dict):
                    current["target"] = {}
                tiers.append(current)
            current = {"target": {}}
            in_target = False
            remainder = stripped[2:].strip()
            if remainder and ":" in remainder:
                key, value = remainder.split(":", 1)
                current[key.strip()] = parse_scalar(value)
            continue

        if current is None:
            continue

        if stripped == "target:":
            in_target = True
            continue

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()

        if in_target and indent >= 6:
            current["target"][key] = parse_scalar(value)
            continue

        in_target = False
        current[key] = parse_scalar(value)

    if current is not None:
        if "target" not in current or not isinstance(current["target"], dict):
            current["target"] = {}
        tiers.append(current)

    return tiers


def load_tiers(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        tiers = parse_tiers_yaml(text)
        if tiers:
            return tiers
    except Exception:
        pass
    return FALLBACK_TIERS


def run_k6(base_url: str, tier_id: str, vus: int, duration: str, out_file: Path) -> dict:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "k6",
        "run",
        "--summary-export",
        str(out_file),
        "-e",
        f"BASE_URL={base_url}",
        "-e",
        f"VUS={vus}",
        "-e",
        f"DURATION={duration}",
        str(K6_SCRIPT),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"k6 failed for {tier_id}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return json.loads(out_file.read_text(encoding="utf-8"))


def metric(summary: dict, name: str, key: str) -> float:
    return float(summary.get("metrics", {}).get(name, {}).get(key, 0.0))


def effective_failed_rate(summary: dict) -> float:
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
    checks = metrics.get("checks", {})
    if isinstance(checks, dict):
        passes = float(checks.get("passes", 0.0) or 0.0)
        fails = float(checks.get("fails", 0.0) or 0.0)
        total = passes + fails
        if total > 0:
            return fails / total
    root_checks = summary.get("root_group", {}).get("checks", {}) if isinstance(summary, dict) else {}
    if isinstance(root_checks, dict) and root_checks:
        passes_sum = 0.0
        fails_sum = 0.0
        for entry in root_checks.values():
            if isinstance(entry, dict):
                passes_sum += float(entry.get("passes", 0.0) or 0.0)
                fails_sum += float(entry.get("fails", 0.0) or 0.0)
        total = passes_sum + fails_sum
        if total > 0:
            return fails_sum / total
    http_req_failed = metrics.get("http_req_failed", {})
    if isinstance(http_req_failed, dict):
        value = http_req_failed.get("value", None)
        if value is not None:
            return float(value)
    return 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tiered capacity load scenarios")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--tiers-file", default=str(TIERS_FILE))
    args = parser.parse_args()

    tiers = load_tiers(Path(args.tiers_file))

    summary_items: list[dict] = []
    generated_at = int(time.time())

    for tier in tiers:
        tier_id = str(tier["id"])
        vus = int(tier["vus"])
        duration = str(tier["duration"])
        failover = bool(tier.get("failover", False))
        target = tier.get("target", {})

        out_file = ROOT / "perf" / "reports" / "tiered" / f"{tier_id}.json"
        k6_summary = run_k6(args.base_url, tier_id, vus, duration, out_file)

        err_rate = effective_failed_rate(k6_summary)
        p90 = metric(k6_summary, "http_req_duration", "p(90)")
        p95 = metric(k6_summary, "http_req_duration", "p(95)")
        p99 = metric(k6_summary, "http_req_duration", "p(99)")

        passed = (
            err_rate <= float(target.get("error_rate_max", 1.0))
            and p90 <= float(target.get("p90_ms_max", 1e9))
            and p95 <= float(target.get("p95_ms_max", 1e9))
            and p99 <= float(target.get("p99_ms_max", 1e9))
        )

        summary_items.append(
            {
                "tier_id": tier_id,
                "vus": vus,
                "duration": duration,
                "failover": failover,
                "metrics": {
                    "http_req_failed_rate": err_rate,
                    "p90_ms": p90,
                    "p95_ms": p95,
                    "p99_ms": p99,
                },
                "target": target,
                "passed": passed,
                "report": str(out_file),
            }
        )

    all_passed = all(item["passed"] for item in summary_items)
    summary = {
        "generated_at": generated_at,
        "base_url": args.base_url,
        "tiers": summary_items,
        "status": "ok" if all_passed else "degraded",
    }

    out = ROOT / "perf" / "reports" / "tiered-capacity-summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[tiered-capacity] summary={out} status={summary['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
