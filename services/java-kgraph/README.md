# Java KGraph Service

该模块对应架构中的 `KGraph Service`（Java/SpringBoot/Spring AI Alibaba方向）。

当前提供三期硬化最小可运行骨架：

- `/kgraph/healthz`
- `/kgraph/reason`

能力层接口（业务/治理平面）：

- `/kgraph/policy/evaluate`
- `/kgraph/aggregate/insights`
- `/kgraph/governance/decision`

gRPC capability 服务：

- 服务名：`ekb.contracts.CapabilityGatewayService`
- 方法：`EvaluatePolicy` / `AggregateInsights` / `GovernanceDecision`
- 端口：`grpc.server.port`（默认 `9091`）
- 代码生成：由 `protobuf-maven-plugin` 从 `contracts/proto/ekb_contracts.proto` 生成 Java/gRPC stubs

兼容桥接（仅联调回退，不是主路径）：

- `/grpc-bridge/capability/EvaluatePolicy`
- `/grpc-bridge/capability/AggregateInsights`
- `/grpc-bridge/capability/GovernanceDecision`

## 构建与测试

```bash
mvn test
```

## 启动

```bash
mvn spring-boot:run
```
