from pathlib import Path


def test_one_click_script_exists_and_references_required_gates() -> None:
    script = Path("scripts/one_click_build_and_deploy.sh")
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "check_dev_toolchain.py" in content
    assert "check_contract_consistency.py" in content
    assert "check_flink_runtime_preflight_contract.py" in content
    assert "check_replay_e2e_slo.py" in content
    assert "bootstrap_deploy_runtime.sh" in content
    assert "docker-compose.phase3.yml" in content or "docker compose -f" in content
    assert "helm upgrade --install ekb-control-plane" in content
