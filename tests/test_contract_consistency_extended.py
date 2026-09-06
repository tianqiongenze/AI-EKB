from scripts.check_contract_consistency import run


def test_contract_consistency_extended_passes() -> None:
    assert run() == 0
