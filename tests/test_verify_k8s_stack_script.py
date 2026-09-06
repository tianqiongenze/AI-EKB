from pathlib import Path


def test_verify_k8s_stack_script_contains_core_service_checks() -> None:
    script = Path("scripts/verify_k8s_stack.py")
    assert script.exists()
    content = script.read_text(encoding="utf-8")
    assert "app=tidb-cluster-tidb" in content
    assert "app=pulsar-broker" in content
    assert "app=redis-cluster" in content
    assert "app=neo4j" in content
    assert "app=milvus" in content
    assert "pulsar-admin" in content
