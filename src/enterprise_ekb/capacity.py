from __future__ import annotations

from math import ceil

from enterprise_ekb.schemas import CapacityEstimateRequest, CapacityEstimateResult


def estimate_capacity(request: CapacityEstimateRequest) -> CapacityEstimateResult:
    estimated_qps = int(request.online_users * request.active_ratio)
    estimated_llm_qps = int(estimated_qps * (1 - request.cache_hit_ratio))
    estimated_heavy_llm_qps = int(estimated_llm_qps * request.complex_ratio)
    estimated_cross_region_qps = int(estimated_qps * request.cross_region_ratio)
    estimated_failover_peak_qps = int(estimated_qps * (1 + request.failover_overhead_ratio))

    tokens_per_second_per_a100 = 1400
    heavy_query_token_budget = 650
    per_gpu_heavy_qps = max(tokens_per_second_per_a100 // heavy_query_token_budget, 1)
    recommended_a100_80g = ceil(estimated_heavy_llm_qps / per_gpu_heavy_qps)

    gateway_qps_per_vcpu = 1800
    control_plane_qps_per_vcpu = 900
    recommended_gateway_vcpu = max(1, ceil(estimated_failover_peak_qps / gateway_qps_per_vcpu))
    recommended_control_plane_vcpu = max(1, ceil(estimated_llm_qps / control_plane_qps_per_vcpu))

    return CapacityEstimateResult(
        estimated_qps=estimated_qps,
        estimated_llm_qps=estimated_llm_qps,
        estimated_heavy_llm_qps=estimated_heavy_llm_qps,
        recommended_a100_80g=recommended_a100_80g,
        estimated_cross_region_qps=estimated_cross_region_qps,
        estimated_failover_peak_qps=estimated_failover_peak_qps,
        recommended_gateway_vcpu=recommended_gateway_vcpu,
        recommended_control_plane_vcpu=recommended_control_plane_vcpu,
    )
