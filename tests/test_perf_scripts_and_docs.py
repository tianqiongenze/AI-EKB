from pathlib import Path


def test_perf_script_and_manual_docs_exist() -> None:
    perf_script = Path("scripts/run_local_long_perf.sh")
    manual_doc = Path("docs/ops/manual-test-access-guide.md")
    report_template = Path("docs/ops/perf-report-template.md")
    assert perf_script.exists()
    assert manual_doc.exists()
    assert report_template.exists()

    content = perf_script.read_text(encoding="utf-8")
    assert "k6 run" in content
    assert "replay-e2e-load-test.js" in content
    assert "load-test.js" in content
