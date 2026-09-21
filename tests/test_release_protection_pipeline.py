import json
import uuid
from pathlib import Path

from scripts.release_protect_artifacts import run


def test_release_protection_verify_and_protect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    baseline = tmp_path / f"baseline-{uuid.uuid4().hex}.json"
    monkeypatch.setenv("EKB_RELEASE_PROTECT_BASELINE_PATH", str(baseline))

    verify_code = run(mode="verify", key="test-key", obfuscation_level=1)
    assert verify_code == 0

    protect_code = run(mode="protect", key="test-key", obfuscation_level=1)
    assert protect_code == 0

    manifest = Path("dist/protected/manifest.json")
    assert manifest.exists()


def test_release_protection_verify_detects_baseline_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    baseline = tmp_path / f"baseline-{uuid.uuid4().hex}.json"
    monkeypatch.setenv("EKB_RELEASE_PROTECT_BASELINE_PATH", str(baseline))

    assert run(mode="verify", key="test-key", obfuscation_level=1) == 0

    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["target_count"] = int(payload["target_count"]) + 1
    baseline.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    assert run(mode="verify", key="test-key", obfuscation_level=1) == 2


def test_release_protection_protect_requires_non_default_key() -> None:
    try:
        run(mode="protect", key="yadea-ekb-default-key", obfuscation_level=1)
        raise AssertionError("expected ValueError for default key")
    except ValueError as exc:
        assert "non-default EKB_RELEASE_PROTECT_KEY" in str(exc)
