from scripts.check_replay_e2e_slo import run


def test_replay_e2e_slo_gate_extended_passes_defaults() -> None:
    assert run() == 0
