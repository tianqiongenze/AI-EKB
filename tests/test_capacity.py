from enterprise_ekb.capacity import estimate_capacity
from enterprise_ekb.schemas import CapacityEstimateRequest


def test_capacity_estimation_basic() -> None:
    result = estimate_capacity(
        CapacityEstimateRequest(
            online_users=1_000_000,
            active_ratio=0.08,
            cache_hit_ratio=0.4,
            complex_ratio=0.3,
        )
    )
    assert result.estimated_qps == 80_000
    assert result.estimated_llm_qps == 48_000
    assert result.estimated_heavy_llm_qps == 14_400
    assert result.estimated_cross_region_qps == 0
    assert result.estimated_failover_peak_qps == 92_000
    assert result.recommended_gateway_vcpu > 0
    assert result.recommended_control_plane_vcpu > 0
    assert result.recommended_a100_80g > 0
