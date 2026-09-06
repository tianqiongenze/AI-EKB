package com.enterprise.ekb.kgraph.grpc;

import com.enterprise.ekb.contracts.proto.CapabilityGatewayServiceGrpc;
import com.google.protobuf.Struct;
import com.google.protobuf.Value;
import io.grpc.ManagedChannel;
import io.grpc.ManagedChannelBuilder;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(properties = "grpc.server.port=0")
class CapabilityGatewayGrpcIntegrationTests {

    @Autowired
    private GrpcServerLifecycle grpcServerLifecycle;

    private ManagedChannel channel;

    @AfterEach
    void tearDownChannel() throws InterruptedException {
        if (channel != null) {
            channel.shutdownNow();
            channel.awaitTermination(3, TimeUnit.SECONDS);
        }
    }

    @Test
    void evaluatePolicyViaGeneratedStubShouldReturnAllowed() {
        int grpcPort = grpcServerLifecycle.getBoundPort();
        assertTrue(grpcPort > 0);

        channel = ManagedChannelBuilder.forAddress("127.0.0.1", grpcPort)
                .usePlaintext()
                .build();
        CapabilityGatewayServiceGrpc.CapabilityGatewayServiceBlockingStub stub =
                CapabilityGatewayServiceGrpc.newBlockingStub(channel);

        Struct attributes = Struct.newBuilder()
                .putFields("criticalAsset", Value.newBuilder().setBoolValue(true).build())
                .putFields("emergency", Value.newBuilder().setBoolValue(true).build())
                .putFields("operation", Value.newBuilder().setStringValue("read").build())
                .build();

        Struct request = Struct.newBuilder()
                .putAllFields(Map.of(
                        "tenant_id", Value.newBuilder().setStringValue("group").build(),
                        "policy_domain", Value.newBuilder().setStringValue("safety").build(),
                        "attributes", Value.newBuilder().setStructValue(attributes).build()
                ))
                .build();

        Struct response = stub.evaluatePolicy(request);
        assertTrue(response.getFieldsOrThrow("allowed").getBoolValue());
        assertTrue(response.getFieldsOrThrow("risk_score").getNumberValue() >= 0);
    }
}
