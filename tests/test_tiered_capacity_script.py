from pathlib import Path

import yaml


def test_tiered_config_exists_and_valid() -> None:
    path = Path("perf/tiered/tiers.yaml")
    assert path.exists()
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    tiers = cfg.get("tiers", [])
    assert isinstance(tiers, list)
    assert len(tiers) >= 5
    ids = {item["id"] for item in tiers}
    assert "tier-0-canary" in ids
    assert "tier-4-global-stress-sim" in ids
