from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class GateResult:
    name: str
    command: list[str]
    exit_code: int
    seconds: float
    stdout_path: str
    stderr_path: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def _run_command(
    name: str,
    command: Sequence[str],
    artifact_dir: Path,
    env: dict[str, str] | None = None,
) -> GateResult:
    started = time.perf_counter()
    safe_name = name.replace("/", "_").replace(" ", "_")
    stdout_path = artifact_dir / f"{safe_name}.stdout.log"
    stderr_path = artifact_dir / f"{safe_name}.stderr.log"
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err, check=False, env=env)
    elapsed = time.perf_counter() - started
    return GateResult(
        name=name,
        command=list(command),
        exit_code=proc.returncode,
        seconds=elapsed,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def _python_bin() -> str:
    candidate = ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def _k6_env_for_phase(phase: str) -> dict[str, str]:
    env = os.environ.copy()
    if phase == "P1":
        env["BASE_URL"] = "http://127.0.0.1:8080"
    elif phase == "P2":
        env["BASE_URL"] = "http://127.0.0.1:8090"
        env["CONTROL_BASE_URL"] = "http://127.0.0.1:8080"
    return env


def _build_phase_commands(
    phase: str,
    records_per_store: int,
    p1_stores: str,
) -> list[tuple[str, list[str]]]:
    py = _python_bin()
    commands: list[tuple[str, list[str]]] = []

    if phase == "P0":
        commands.extend(
            [
                ("pytest", [py, "-m", "pytest", "-q"]),
                ("replay_slo_gate", [py, "scripts/check_replay_e2e_slo.py"]),
                ("gateway_slo_gate", [py, "scripts/check_gateway_slo.py"]),
            ]
        )
    elif phase == "P1":
        commands.extend(
            [
                (
                    "seed_1m",
                    [
                        py,
                        "scripts/seed_large_scale_data.py",
                        "--stores",
                        p1_stores,
                        "--records-per-store",
                        str(records_per_store),
                        "--summary-path",
                        "perf/reports/seed-latest-summary.json",
                    ],
                ),
                (
                    "store_benchmark",
                    [
                        py,
                        "scripts/benchmark_store_operations.py",
                        "--samples",
                        "500",
                        "--stores",
                        p1_stores,
                        "--summary-path",
                        "perf/reports/store-benchmark-latest.json",
                    ],
                ),
                (
                    "replay_no_thresholds",
                    [
                        "k6",
                        "run",
                        "--no-thresholds",
                        "--summary-trend-stats",
                        "avg,min,med,max,p(90),p(95),p(99)",
                        "--summary-export",
                        "perf/reports/replay-latest-summary.json",
                        "perf/k6/replay-e2e-load-test.js",
                    ],
                ),
            ]
        )
    elif phase == "P2":
        commands.extend(
            [
                (
                    "load_no_thresholds",
                    [
                        "k6",
                        "run",
                        "--no-thresholds",
                        "--summary-trend-stats",
                        "avg,min,med,max,p(90),p(95),p(99)",
                        "--summary-export",
                        "perf/reports/load-latest-summary.json",
                        "perf/k6/load-test.js",
                    ],
                ),
                ("generate_gateway_perf_summary", [py, "scripts/generate_gateway_perf_summary.py"]),
                ("gateway_perf_report_gate", [py, "scripts/check_gateway_perf_report.py"]),
            ]
        )
    elif phase == "P3":
        commands.extend(
            [
                (
                    "architecture_dr_docs_check",
                    [
                        py,
                        "-c",
                        (
                            "from pathlib import Path;"
                            "req=['docs/global-deployment-and-dr.md','docs/phase3-hardening-architecture.md'];"
                            "missing=[p for p in req if not Path(p).exists()];"
                            "print('missing',missing);"
                            "raise SystemExit(1 if missing else 0)"
                        ),
                    ],
                )
            ]
        )
    else:
        raise ValueError(f"unsupported phase: {phase}")

    return commands


def _command_env(phase: str, name: str) -> dict[str, str] | None:
    if name in {"replay_no_thresholds", "load_no_thresholds"}:
        return _k6_env_for_phase(phase)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run phased capacity and HA gates (P0-P3)")
    parser.add_argument("--phase", choices=["P0", "P1", "P2", "P3", "ALL"], default="ALL")
    parser.add_argument("--records-per-store", type=int, default=1_000_000)
    parser.add_argument(
        "--p1-stores",
        type=str,
        default="tidb,redis,neo4j,milvus",
        help="stores used for P1 seeding/benchmark",
    )
    parser.add_argument("--artifact-dir", type=str, default="perf/artifacts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    phases = ["P0", "P1", "P2", "P3"] if args.phase == "ALL" else [args.phase]
    run_dir = ROOT / args.artifact_dir / f"capacity-ha-{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, list[GateResult]] = {}
    failed = False

    for phase in phases:
        phase_results: list[GateResult] = []
        phase_dir = run_dir / phase
        phase_dir.mkdir(parents=True, exist_ok=True)
        print(f"[gates] phase={phase}")
        for name, command in _build_phase_commands(phase, args.records_per_store, args.p1_stores):
            print(f"[gates] run {name}: {' '.join(command)}")
            result = _run_command(
                name=name,
                command=command,
                artifact_dir=phase_dir,
                env=_command_env(phase, name),
            )
            phase_results.append(result)
            print(f"[gates] {name} exit={result.exit_code} seconds={result.seconds:.2f}")
            if result.exit_code != 0:
                failed = True

        all_results[phase] = phase_results

    summary = {
        "generated_at": int(time.time()),
        "phases": {
            phase: [
                {
                    "name": r.name,
                    "command": r.command,
                    "exit_code": r.exit_code,
                    "seconds": round(r.seconds, 3),
                    "passed": r.passed,
                    "stdout_path": r.stdout_path,
                    "stderr_path": r.stderr_path,
                }
                for r in results
            ]
            for phase, results in all_results.items()
        },
        "passed": not failed,
    }
    summary_path = run_dir / "capacity-ha-summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gates] summary: {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
