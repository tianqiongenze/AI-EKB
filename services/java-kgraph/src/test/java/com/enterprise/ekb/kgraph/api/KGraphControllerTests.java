package com.enterprise.ekb.kgraph.api;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "grpc.server.port=0")
@AutoConfigureMockMvc
class KGraphControllerTests {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void healthzShouldReturnOk() throws Exception {
        mockMvc.perform(get("/kgraph/healthz"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"));
    }

    @Test
    void reasonShouldReturnResults() throws Exception {
        String payload = """
                {
                  "tenantId": "group",
                  "plantId": "plant-a",
                  "query": "分析工艺异常",
                  "evidenceRefs": ["doc-1", "doc-2"]
                }
                """;

        mockMvc.perform(post("/kgraph/reason")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.engine").value("spring-ai-alibaba-adapter"))
                .andExpect(jsonPath("$.results[0]").value("entity:设备"));
    }

    @Test
    void reasonShouldFallbackWhenQueryTooLong() throws Exception {
        String longQuery = "x".repeat(2049);
        String payload = """
                {
                  "tenantId": "group",
                  "plantId": "plant-a",
                  "query": "%s",
                  "evidenceRefs": ["doc-1"]
                }
                """.formatted(longQuery);

        mockMvc.perform(post("/kgraph/reason")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.results[0]").value("fallback:sentinel-triggered"));
    }

    @Test
    void evaluatePolicyShouldReturnDecision() throws Exception {
        String payload = """
                {
                  "tenantId": "group",
                  "policyDomain": "safety",
                  "attributes": {"criticalAsset": true, "emergency": true, "operation": "read"}
                }
                """;

        mockMvc.perform(post("/kgraph/policy/evaluate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.allowed").value(true));
    }

    @Test
    void aggregateInsightsShouldReturnSummary() throws Exception {
        String payload = """
                {
                  "tenantId": "group",
                  "query": "分析工艺异常",
                  "evidenceRefs": ["doc-1", "doc-2"]
                }
                """;

        mockMvc.perform(post("/kgraph/aggregate/insights")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.summary.reasoning_items").exists());
    }

    @Test
    void governanceDecisionShouldReturnControls() throws Exception {
        String payload = """
                {
                  "tenantId": "group",
                  "regionId": "cn-north-1",
                  "action": "release",
                  "riskScore": 90
                }
                """;

        mockMvc.perform(post("/kgraph/governance/decision")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.decision").value("manual_approval_required"));
    }

    @Test
    void grpcBridgeEvaluatePolicyEndpointShouldReturnAllowed() throws Exception {
        String payload = """
                {
                  "tenant_id": "group",
                  "policy_domain": "safety",
                  "attributes": {"criticalAsset": true, "emergency": true, "operation": "read"}
                }
                """;

        mockMvc.perform(post("/grpc-bridge/capability/EvaluatePolicy")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.allowed").value(true));
    }
}
