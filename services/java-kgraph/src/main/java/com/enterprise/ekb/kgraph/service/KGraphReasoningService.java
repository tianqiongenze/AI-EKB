package com.enterprise.ekb.kgraph.service;

import com.alibaba.csp.sentinel.annotation.SentinelResource;
import org.neo4j.driver.AuthTokens;
import org.neo4j.driver.Driver;
import org.neo4j.driver.GraphDatabase;
import org.neo4j.driver.Record;
import org.neo4j.driver.Result;
import org.neo4j.driver.Session;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class KGraphReasoningService {

    private final Driver neo4jDriver;

    public KGraphReasoningService() {
        String uri = System.getProperty("EKB_NEO4J_URI", System.getenv().getOrDefault("EKB_NEO4J_URI", "bolt://127.0.0.1:7687"));
        String username = System.getProperty("EKB_NEO4J_USERNAME", System.getenv().getOrDefault("EKB_NEO4J_USERNAME", "neo4j"));
        String password = System.getProperty("EKB_NEO4J_PASSWORD", System.getenv().getOrDefault("EKB_NEO4J_PASSWORD", ""));
        if (password.isEmpty()) {
            this.neo4jDriver = null;
        } else {
            this.neo4jDriver = GraphDatabase.driver(uri, AuthTokens.basic(username, password));
        }
    }

    @SentinelResource(value = "kgraph_reason", fallback = "fallbackReason")
    public List<String> reason(String query, List<String> evidenceRefs) {
        if (query.length() > 2048) {
            throw new IllegalArgumentException("query too long");
        }
        if (neo4jDriver != null) {
            List<String> graphResult = fetchFromGraph(query, evidenceRefs);
            if (!graphResult.isEmpty()) {
                return graphResult;
            }
        }
        // Explicit degradation markers instead of fabricated knowledge: callers
        // and SLO monitors must be able to tell degraded output from graph truth.
        List<String> degraded = new ArrayList<>();
        degraded.add(neo4jDriver == null ? "degraded:neo4j_unavailable" : "degraded:graph_empty_result");
        if (evidenceRefs != null && !evidenceRefs.isEmpty()) {
            degraded.add("evidence:" + evidenceRefs.get(0));
        }
        return degraded;
    }

    private List<String> fetchFromGraph(String query, List<String> evidenceRefs) {
        String cypher = "MATCH (a:Entity)-[r:RELATED]->(b:Entity) " +
                "WHERE a.id CONTAINS $query OR b.id CONTAINS $query " +
                "RETURN a.id AS source, r.type AS relationType, b.id AS target LIMIT 5";
        List<String> results = new ArrayList<>();
        try (Session session = neo4jDriver.session()) {
            Result result = session.run(cypher, org.neo4j.driver.Values.parameters("query", query));
            while (result.hasNext()) {
                Record record = result.next();
                results.add("entity:" + record.get("source").asString());
                results.add("relation:" + record.get("relationType").asString());
                results.add("entity:" + record.get("target").asString());
            }
        }
        if (!evidenceRefs.isEmpty() && !results.isEmpty()) {
            results.add("evidence:" + evidenceRefs.get(0));
        }
        return results;
    }

    public List<String> fallbackReason(String query, List<String> evidenceRefs, Throwable throwable) {
        return List.of(
                "fallback:sentinel-triggered",
                "fallback:use-cached-knowledge"
        );
    }

    public PolicyEvaluationResult evaluatePolicy(String tenantId, String policyDomain, Map<String, Object> attributes) {
        boolean criticalAsset = Boolean.TRUE.equals(attributes.get("criticalAsset"));
        boolean emergency = Boolean.TRUE.equals(attributes.get("emergency"));
        String operation = String.valueOf(attributes.getOrDefault("operation", "read"));

        boolean allowed = ("safety".equals(policyDomain) && emergency)
                || (!criticalAsset && ("read".equals(operation) || "query".equals(operation)));

        List<String> reasons = new ArrayList<>();
        if (allowed) {
            reasons.add("policy:allowed");
            reasons.add("tenant:" + tenantId);
        } else {
            reasons.add("policy:denied");
            reasons.add("reason:critical_asset_requires_manual_approval");
        }

        int riskScore = criticalAsset ? 85 : 35;
        if (emergency) {
            riskScore = Math.max(20, riskScore - 30);
        }

        return new PolicyEvaluationResult(allowed, riskScore, reasons);
    }

    public AggregationResult aggregateInsights(String tenantId, String query, List<String> evidenceRefs) {
        List<String> reasoning = reason(query, evidenceRefs);
        Map<String, Integer> summary = new LinkedHashMap<>();
        summary.put("reasoning_items", reasoning.size());
        summary.put("evidence_count", evidenceRefs.size());
        summary.put("confidence", Math.min(95, 60 + evidenceRefs.size() * 5));
        return new AggregationResult(tenantId, query, summary, reasoning);
    }

    public GovernanceDecision evaluateGovernanceGate(String tenantId, String regionId, String action, int riskScore) {
        boolean requiresApproval = riskScore >= 80;
        String decision = requiresApproval ? "manual_approval_required" : "auto_approved";
        List<String> controls = requiresApproval
                ? List.of("two-person-review", "audit-log", "time-boxed-token")
                : List.of("audit-log", "standard-token");
        return new GovernanceDecision(tenantId, regionId, action, decision, controls);
    }

    public record PolicyEvaluationResult(boolean allowed, int riskScore, List<String> reasons) {
    }

    public record AggregationResult(String tenantId, String query, Map<String, Integer> summary, List<String> insights) {
    }

    public record GovernanceDecision(String tenantId, String regionId, String action, String decision, List<String> controls) {
    }
}
