from scripts.check_flink_runtime_preflight_contract import run


def test_flink_runtime_preflight_contract_passes() -> None:
    assert run() == 0
