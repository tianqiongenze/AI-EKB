from pathlib import Path


def test_smoke_k8s_workflow_runs_one_click_k8s() -> None:
    workflow = Path(".github/workflows/smoke-one-click-k8s-kind.yml")
    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "one_click_build_and_deploy.sh k8s" in content
    assert "verify_k8s_stack.py" in content
    assert "kind" in content
