package com.enterprise.ekb.kgraph.grpc;

import com.enterprise.ekb.kgraph.service.KGraphReasoningService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/grpc-bridge/capability")
public class CapabilityGrpcBridgeController {

    private final KGraphReasoningService reasoningService;

    public CapabilityGrpcBridgeController(KGraphReasoningService reasoningService) {
        this.reasoningService = reasoningService;
    }

    @PostMapping(value = "/EvaluatePolicy", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> evaluatePolicy(@RequestBody Map<String, Object> payload) {
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String policyDomain = String.valueOf(payload.getOrDefault("policy_domain", "safety"));
        Map<String, Object> attributes = CapabilityGrpcMappingSupport.mapValue(payload.get("attributes"));

        KGraphReasoningService.PolicyEvaluationResult result = reasoningService.evaluatePolicy(tenantId, policyDomain, attributes);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("allowed", result.allowed());
        response.put("risk_score", result.riskScore());
        response.put("reasons", result.reasons());
        response.put("transport", "grpc-bridge-http-json");
        return response;
    }

    @PostMapping(value = "/AggregateInsights", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> aggregateInsights(@RequestBody Map<String, Object> payload) {
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String query = String.valueOf(payload.getOrDefault("query", ""));
        var evidenceRefs = CapabilityGrpcMappingSupport.listValue(payload.get("evidence_refs"));

        KGraphReasoningService.AggregationResult result = reasoningService.aggregateInsights(tenantId, query, evidenceRefs);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("summary", result.summary());
        response.put("insights", result.insights());
        response.put("transport", "grpc-bridge-http-json");
        return response;
    }

    @PostMapping(value = "/GovernanceDecision", consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> governanceDecision(@RequestBody Map<String, Object> payload) {
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String regionId = String.valueOf(payload.getOrDefault("region_id", ""));
        String action = String.valueOf(payload.getOrDefault("action", ""));
        int riskScore = ((Number) payload.getOrDefault("risk_score", 0)).intValue();

        KGraphReasoningService.GovernanceDecision result = reasoningService.evaluateGovernanceGate(tenantId, regionId, action, riskScore);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("decision", result.decision());
        response.put("controls", result.controls());
        response.put("transport", "grpc-bridge-http-json");
        return response;
    }

}
