from pathlib import Path


def test_flink_session_image_contains_preflight_requirements() -> None:
    dockerfile = Path("services/flink-session-image/Dockerfile")
    assert dockerfile.exists()
    content = dockerfile.read_text(encoding="utf-8")
    assert "install -y --no-install-recommends python3" in content
    assert "iceberg-flink-runtime" in content
    assert "iceberg-nessie" in content
    assert "hadoop-aws" in content
    assert "aws-java-sdk-bundle" in content
