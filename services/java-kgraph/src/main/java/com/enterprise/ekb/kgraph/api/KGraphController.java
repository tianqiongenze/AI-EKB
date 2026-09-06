package com.enterprise.ekb.kgraph.api;

import com.enterprise.ekb.kgraph.service.KGraphReasoningService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@Validated
@RestController
@RequestMapping("/kgraph")
public class KGraphController {

    private final KGraphReasoningService reasoningService;

    public KGraphController(KGraphReasoningService reasoningService) {
        this.reasoningService = reasoningService;
    }

    @GetMapping("/healthz")
    public Map<String, String> healthz() {
        return Map.of("status", "ok");
    }

    @PostMapping("/reason")
    public KGraphReasonResponse reason(@Valid @RequestBody KGraphReasonRequest request) {
        List<String> results;
        try {
            results = reasoningService.reason(request.query(), request.evidenceRefs());
        } catch (RuntimeException exception) {
            results = reasoningService.fallbackReason(request.query(), request.evidenceRefs(), exception);
        }

        return new KGraphReasonResponse(
                request.tenantId(),
                request.plantId(),
                "spring-ai-alibaba-adapter",
                results
        );
    }

    @PostMapping("/policy/evaluate")
    public PolicyEvaluationResponse evaluatePolicy(@Valid @RequestBody PolicyEvaluationRequest request) {
        KGraphReasoningService.PolicyEvaluationResult result = reasoningService.evaluatePolicy(
                request.tenantId(),
                request.policyDomain(),
                request.attributes()
        );
        return new PolicyEvaluationResponse(
                request.tenantId(),
                request.policyDomain(),
                result.allowed(),
                result.riskScore(),
                result.reasons()
        );
    }

    @PostMapping("/aggregate/insights")
    public AggregationResponse aggregateInsights(@Valid @RequestBody AggregationRequest request) {
        KGraphReasoningService.AggregationResult result = reasoningService.aggregateInsights(
                request.tenantId(),
                request.query(),
                request.evidenceRefs()
        );
        return new AggregationResponse(
                result.tenantId(),
                result.query(),
                result.summary(),
                result.insights()
        );
    }

    @PostMapping("/governance/decision")
    public GovernanceDecisionResponse governanceDecision(@Valid @RequestBody GovernanceDecisionRequest request) {
        KGraphReasoningService.GovernanceDecision result = reasoningService.evaluateGovernanceGate(
                request.tenantId(),
                request.regionId(),
                request.action(),
                request.riskScore()
        );
        return new GovernanceDecisionResponse(
                result.tenantId(),
                result.regionId(),
                result.action(),
                result.decision(),
                result.controls()
        );
    }

    public record KGraphReasonRequest(
            @NotBlank String tenantId,
            @NotBlank String plantId,
            @NotBlank String query,
            @NotEmpty List<String> evidenceRefs
    ) {
    }

    public record KGraphReasonResponse(
            String tenantId,
            String plantId,
            String engine,
            List<String> results
    ) {
    }

    public record PolicyEvaluationRequest(
            @NotBlank String tenantId,
            @NotBlank String policyDomain,
            Map<String, Object> attributes
    ) {
    }

    public record PolicyEvaluationResponse(
            String tenantId,
            String policyDomain,
            boolean allowed,
            int riskScore,
            List<String> reasons
    ) {
    }

    public record AggregationRequest(
            @NotBlank String tenantId,
            @NotBlank String query,
            @NotEmpty List<String> evidenceRefs
    ) {
    }

    public record AggregationResponse(
            String tenantId,
            String query,
            Map<String, Integer> summary,
            List<String> insights
    ) {
    }

    public record GovernanceDecisionRequest(
            @NotBlank String tenantId,
            @NotBlank String regionId,
            @NotBlank String action,
            int riskScore
    ) {
    }

    public record GovernanceDecisionResponse(
            String tenantId,
            String regionId,
            String action,
            String decision,
            List<String> controls
    ) {
    }
}
