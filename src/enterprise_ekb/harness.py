from __future__ import annotations

from enterprise_ekb.schemas import HarnessEvaluationRequest, HarnessEvaluationResult


class HarnessGate:
    def __init__(
        self,
        quality_threshold: float = 0.82,
        safety_threshold: float = 0.92,
        regression_threshold: float = 0.88,
        max_latency_ms: int = 2200,
    ) -> None:
        self.quality_threshold = quality_threshold
        self.safety_threshold = safety_threshold
        self.regression_threshold = regression_threshold
        self.max_latency_ms = max_latency_ms

    def evaluate(self, request: HarnessEvaluationRequest) -> HarnessEvaluationResult:
        reasons: list[str] = []
        if request.quality_score < self.quality_threshold:
            reasons.append("quality_gate_failed")
        if request.safety_score < self.safety_threshold:
            reasons.append("safety_gate_failed")
        if request.regression_score < self.regression_threshold:
            reasons.append("regression_gate_failed")
        if request.latency_ms > self.max_latency_ms:
            reasons.append("latency_gate_failed")

        accepted = len(reasons) == 0
        gate_scores = {
            "quality": request.quality_score,
            "safety": request.safety_score,
            "regression": request.regression_score,
            "latency_ms": float(request.latency_ms),
        }
        return HarnessEvaluationResult(
            accepted=accepted,
            reasons=reasons,
            gate_scores=gate_scores,
        )
