from pathlib import Path


def test_build_push_workflow_waits_for_ci_multilang_success() -> None:
    workflow = Path(".github/workflows/build-and-push-flink-session.yml")
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "workflow_run" in content
    assert "workflows: [\"ci-multilang\"]" in content
    assert "conclusion == 'success'" in content
