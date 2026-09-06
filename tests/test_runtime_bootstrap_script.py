from pathlib import Path


def test_runtime_bootstrap_script_supports_local_and_k8s_modes() -> None:
    script = Path("scripts/bootstrap_deploy_runtime.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "MODE=\"${1:-local}\"" in content
    assert "docker" in content
    assert "kubectl" in content
    assert "helm" in content
    assert "apt-get" in content or "brew" in content
