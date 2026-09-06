from pathlib import Path


def test_bootstrap_installs_required_yaml_and_python_deps() -> None:
    script = Path("scripts/bootstrap_dev_toolchain.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "yaml-language-server" in content
    assert "pyyaml" in content
    assert "grpcio-tools" in content
