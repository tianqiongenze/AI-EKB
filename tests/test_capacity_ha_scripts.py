from pathlib import Path


def test_capacity_ha_scripts_exist() -> None:
    seed_script = Path("scripts/seed_large_scale_data.py")
    bench_script = Path("scripts/benchmark_store_operations.py")
    gate_script = Path("scripts/run_capacity_ha_gates.py")
    impl_doc = Path("docs/ops/p0-p3-capacity-ha-implementation.md")

    assert seed_script.exists()
    assert bench_script.exists()
    assert gate_script.exists()
    assert impl_doc.exists()


def test_capacity_ha_script_content_contract() -> None:
    seed_content = Path("scripts/seed_large_scale_data.py").read_text(encoding="utf-8")
    bench_content = Path("scripts/benchmark_store_operations.py").read_text(encoding="utf-8")
    gate_content = Path("scripts/run_capacity_ha_gates.py").read_text(encoding="utf-8")

    assert "--records-per-store" in seed_content
    assert "1_000_000" in seed_content
    assert "seed-latest-summary.json" in seed_content

    assert "store-benchmark-latest.json" in bench_content
    assert "p95" in bench_content
    assert "p99" in bench_content

    assert "P0" in gate_content
    assert "P1" in gate_content
    assert "P2" in gate_content
    assert "P3" in gate_content
    assert "capacity-ha-summary.json" in gate_content
