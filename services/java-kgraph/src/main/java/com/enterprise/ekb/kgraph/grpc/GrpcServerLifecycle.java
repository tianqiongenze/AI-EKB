package com.enterprise.ekb.kgraph.grpc;

import io.grpc.Server;
import io.grpc.ServerBuilder;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.event.ContextClosedEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.util.concurrent.TimeUnit;

@Component
public class GrpcServerLifecycle {

    private final CapabilityGatewayGrpcService capabilityGatewayGrpcService;

    @Value("${grpc.server.port:9091}")
    private int grpcPort;

    private Server server;

    public GrpcServerLifecycle(CapabilityGatewayGrpcService capabilityGatewayGrpcService) {
        this.capabilityGatewayGrpcService = capabilityGatewayGrpcService;
    }

    @PostConstruct
    public void start() throws IOException {
        int selectedPort = grpcPort;
        if (selectedPort < 0) {
            selectedPort = 9091;
        }
        server = ServerBuilder.forPort(selectedPort)
                .addService(capabilityGatewayGrpcService.bindService())
                .build()
                .start();
    }

    public int getBoundPort() {
        if (server == null) {
            return -1;
        }
        return server.getPort();
    }

    @EventListener
    public void onContextClosed(ContextClosedEvent event) throws InterruptedException {
        stop();
    }

    @PreDestroy
    public void stop() throws InterruptedException {
        if (server == null) {
            return;
        }
        server.shutdown();
        server.awaitTermination(3, TimeUnit.SECONDS);
    }
}
