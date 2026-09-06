package com.enterprise.ekb.kgraph.service;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class KGraphReasoningServiceIntegrationTests {

    @Test
    void reasonShouldWorkWithNeo4jConfigFallback() {
        System.setProperty("EKB_NEO4J_URI", "bolt://127.0.0.1:7687");
        System.setProperty("EKB_NEO4J_USERNAME", "neo4j");
        System.setProperty("EKB_NEO4J_PASSWORD", "");
        KGraphReasoningService service = new KGraphReasoningService();
        List<String> result = service.reason("工艺异常", List.of("doc-1"));
        assertFalse(result.isEmpty());
    }

    @Test
    void policyAndGovernanceShouldWork() {
        KGraphReasoningService service = new KGraphReasoningService();
        KGraphReasoningService.PolicyEvaluationResult policyResult = service.evaluatePolicy(
                "group",
                "safety",
                Map.of("criticalAsset", true, "emergency", true, "operation", "read")
        );
        assertTrue(policyResult.allowed());

        KGraphReasoningService.GovernanceDecision decision = service.evaluateGovernanceGate(
                "group",
                "cn-north-1",
                "release",
                90
        );
        assertEquals("manual_approval_required", decision.decision());
    }
}
