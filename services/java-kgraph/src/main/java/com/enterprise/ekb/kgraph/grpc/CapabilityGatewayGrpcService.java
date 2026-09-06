package com.enterprise.ekb.kgraph.grpc;

import com.enterprise.ekb.contracts.proto.CapabilityGatewayServiceGrpc;
import com.enterprise.ekb.kgraph.service.KGraphReasoningService;
import com.google.protobuf.Struct;
import io.grpc.stub.StreamObserver;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

@Component
public class CapabilityGatewayGrpcService extends CapabilityGatewayServiceGrpc.CapabilityGatewayServiceImplBase {

    private final KGraphReasoningService reasoningService;

    public CapabilityGatewayGrpcService(KGraphReasoningService reasoningService) {
        this.reasoningService = reasoningService;
    }

    @Override
    public void evaluatePolicy(Struct request, StreamObserver<Struct> responseObserver) {
        Map<String, Object> payload = CapabilityGrpcMappingSupport.structToMap(request);
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String policyDomain = String.valueOf(payload.getOrDefault("policy_domain", "safety"));
        Map<String, Object> attributes = CapabilityGrpcMappingSupport.mapValue(payload.get("attributes"));

        KGraphReasoningService.PolicyEvaluationResult result = reasoningService.evaluatePolicy(tenantId, policyDomain, attributes);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("allowed", result.allowed());
        response.put("risk_score", result.riskScore());
        response.put("reasons", result.reasons());

        responseObserver.onNext(CapabilityGrpcMappingSupport.mapToStruct(response));
        responseObserver.onCompleted();
    }

    @Override
    public void aggregateInsights(Struct request, StreamObserver<Struct> responseObserver) {
        Map<String, Object> payload = CapabilityGrpcMappingSupport.structToMap(request);
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String query = String.valueOf(payload.getOrDefault("query", ""));
        var evidenceRefs = CapabilityGrpcMappingSupport.listValue(payload.get("evidence_refs"));

        KGraphReasoningService.AggregationResult result = reasoningService.aggregateInsights(tenantId, query, evidenceRefs);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("summary", result.summary());
        response.put("insights", result.insights());

        responseObserver.onNext(CapabilityGrpcMappingSupport.mapToStruct(response));
        responseObserver.onCompleted();
    }

    @Override
    public void governanceDecision(Struct request, StreamObserver<Struct> responseObserver) {
        Map<String, Object> payload = CapabilityGrpcMappingSupport.structToMap(request);
        String tenantId = String.valueOf(payload.getOrDefault("tenant_id", ""));
        String regionId = String.valueOf(payload.getOrDefault("region_id", ""));
        String action = String.valueOf(payload.getOrDefault("action", ""));
        int riskScore = CapabilityGrpcMappingSupport.numberValue(payload.get("risk_score"));

        KGraphReasoningService.GovernanceDecision result = reasoningService.evaluateGovernanceGate(tenantId, regionId, action, riskScore);
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("decision", result.decision());
        response.put("controls", result.controls());

        responseObserver.onNext(CapabilityGrpcMappingSupport.mapToStruct(response));
        responseObserver.onCompleted();
    }
}
