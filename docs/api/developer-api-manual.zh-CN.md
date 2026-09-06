# 开发者 API 手册（中文）

## 1. 项目总览

Yadea EKB 控制面提供技能治理、MCP 调用治理、A2A 消息分发、图谱与向量写入/检索、审计追踪等能力。

## 2. Python 模块与函数清单（完整）

### `src/enterprise_ekb/app.py`
- `create_app(db_path=None)`: 创建并装配 FastAPI 应用与所有依赖。
- `healthz()`: 健康检查。
- `readyz()`: 就绪检查，返回存储与 outbox 状态。
- `register_skill(...)`: 注册技能并投递事件。
- `promote_skill(...)`: 技能阶段晋级并投递事件。
- `mcp_invoke(...)`: MCP 调用入口，包含认证、限流、策略校验、审计。
- `evaluate_harness(...)`: Harness 评测入口。
- `capacity_estimate(...)`: 容量估算入口。
- `query_audit(...)`: 审计查询入口。
- `relay_events(...)`: Outbox 事件转发。
- `publish_a2a(...)`: 发布 A2A 消息。
- `consume_a2a(...)`: 消费一条 A2A 消息。
- `graph_upsert(...)`: 图关系写入。
- `vector_upsert(...)`: 向量写入。
- `vector_search(...)`: 向量检索。

### `src/enterprise_ekb/schemas.py`
- `SkillRiskLevel` / `SkillStage`: 技能风险与阶段枚举。
- `SkillManifest`: 技能清单模型。
- `SkillPromotionRequest`: 技能晋级请求。
- `AuditQuery`: 审计查询请求。
- `GatewayInvokeRequest`: MCP 调用请求。
- `HarnessEvaluationRequest` / `HarnessEvaluationResult`: Harness 请求与结果。
- `CapacityEstimateRequest` / `CapacityEstimateResult`: 容量估算请求与结果。
- `RelayRequest`: Outbox relay 请求。
- `A2AEnvelope`: A2A 消息封装。
- `GraphRelation` / `GraphUpsertRequest`: 图谱写入模型。
- `VectorUpsertRequest` / `VectorSearchRequest` / `VectorSearchResult`: 向量写入与检索模型。

### `src/enterprise_ekb/a2a_runtime.py`
- `A2AConsumerConfig`: A2A 消费器配置。
- `A2ADispatcher.register(intent, handler)`: 注册 intent 处理器。
- `A2ADispatcher.dispatch(payload)`: 根据 intent 分发执行。
- `A2AConsumer.run_once()`: 消费一条消息并 dispatch。
- `A2AConsumer.close()`: 释放连接。
- `build_a2a_consumer(config)`: 构建默认消费者。

### `src/enterprise_ekb/config.py`
- `AppConfig`: 控制面配置模型。
- `load_config()`: 从环境变量加载配置。

### `src/enterprise_ekb/rate_limiter.py`
- `RateLimitResult`: 限流判定结果。
- `TokenBucketRateLimiter.allow(tokens=1)`: 令牌桶限流判定。

### `src/enterprise_ekb/event_bus.py`
- `EventPublisher`（协议）: 事件发布器接口。
- `InMemoryPublisher`: 内存发布器。
- `PulsarPublisher`: Pulsar 发布器。
- `OutboxRelay.run_once(batch_size=100)`: 扫描 outbox 并发布。

### `src/enterprise_ekb/middleware_clients.py`
- `RedisConfig/PulsarConfig/Neo4jConfig/MilvusConfig`: 中间件配置模型。
- `HighPerformanceRedisClient`: Redis 批量读取/写入。
- `HighPerformanceNeo4jClient`: 图关系批量写入。
- `HighPerformanceMilvusClient`: 向量写入与检索。
- `HighPerformancePulsarClient`: Pulsar 批量发布。

### `src/enterprise_ekb/storage.py`
- `SkillRow`, `OutboxEvent`: 存储结构。
- `SQLiteControlPlaneStore`: 控制面 SQLite 存储实现。

### `src/enterprise_ekb/tidb_store.py`
- `TiDBControlPlaneStore`: 控制面 TiDB 存储实现。

### 其他模块
- `migrator.py`: TiDB 迁移执行器。
- `skill_registry.py`: 技能注册/晋级状态机。
- `capacity.py`: 并发与资源估算。
- `harness.py`: 质量/安全/回归门禁。
- `mcp_gateway.py`: MCP 调用封装。
- `policy.py`: 策略引擎。

## 3. Go 结构体与方法清单

### `services/go-gateway/main.go`
- `HealthResponse`
- `GatewayRuntimeConfig`
- `CacheAdapter`, `EventAdapter`, `GraphAdapter`, `VectorAdapter`
- `RedisCacheAdapter` + `GetMany` + `SetManyWithTTL`
- `PulsarEventAdapter` + `PublishBatch` + `getOrCreateProducer`
- `CircuitBreaker` + `Allow` + `Report`
- `GraphEdge`, `VectorHit`
- `NoopCacheAdapter`, `NoopEventAdapter`, `NoopGraphAdapter`, `NoopVectorAdapter`
- `TokenBucketRateLimiter` + `Allow`
- `loadGatewayRuntimeConfig()`
- 中间件封装：`withGlobalRateLimit`、`withBackpressure`、`withTimeout`
- `executeWithRetry(...)`
- `chain(...)`
- `GatewayServer.routes()`
- `writeJSON(...)`
- `main()`
- gRPC 能力调用适配：`grpcCapabilityAdapter`、`CapabilityGatewayServiceClient`
- 指标端点：`GET /metrics/gateway`（可配置）

## 4. Java 类与方法清单

### `services/java-kgraph/src/main/java/...`
- `KGraphApplication.main(...)`: SpringBoot 启动入口。
- `KGraphController.healthz()`: 健康检查。
- `KGraphController.reason(...)`: 推理入口，失败时 fallback。
- `KGraphController.evaluatePolicy(...)`: 复杂策略评估入口。
- `KGraphController.aggregateInsights(...)`: 复杂聚合入口。
- `KGraphController.governanceDecision(...)`: 治理决策入口。
- `KGraphReasoningService.reason(...)`: 推理主逻辑（含 Sentinel 保护）。
- `KGraphReasoningService.fallbackReason(...)`: 退化逻辑。
- `KGraphReasoningService.fetchFromGraph(...)`: Neo4j 查询逻辑。
- `KGraphReasoningService.evaluatePolicy(...)`: 复杂策略评估。
- `KGraphReasoningService.aggregateInsights(...)`: 聚合洞察。
- `KGraphReasoningService.evaluateGovernanceGate(...)`: 治理门禁决策。

新增 Java 能力层接口：

- `POST /kgraph/policy/evaluate`
- `POST /kgraph/aggregate/insights`
- `POST /kgraph/governance/decision`

Java 能力层 gRPC 服务：

- 服务：`ekb.contracts.CapabilityGatewayService`
- RPC：`EvaluatePolicy`、`AggregateInsights`、`GovernanceDecision`
- 端口：`grpc.server.port`（默认 `9091`）
- Java stubs：由 Maven 构建阶段通过 `protobuf-maven-plugin` 从 `contracts/proto/ekb_contracts.proto` 自动生成

兼容桥接接口（仅联调/回退）：

- `POST /grpc-bridge/capability/EvaluatePolicy`
- `POST /grpc-bridge/capability/AggregateInsights`
- `POST /grpc-bridge/capability/GovernanceDecision`

## 5. API 端点

- `GET /healthz`
- `GET /readyz`
- `POST /skills/register`
- `POST /skills/promote`
- `POST /mcp/invoke`
- `POST /harness/evaluate`
- `POST /capacity/estimate`
- `POST /audit/query`
- `POST /events/relay`
- `POST /a2a/publish`
- `POST /a2a/consume`
- `POST /graph/upsert`
- `POST /vector/upsert`
- `POST /vector/search`

## 6. CI 运行时验证

- Java 流水线包含 Neo4j 集成验证路径。
- Go 流水线包含 Pulsar 发布路径与限流行为验证。
- release-gate 强制校验契约与双语手册完整性。
- release-gate 执行 `pre-commit run --all-files`。
- release-gate 通过 `scripts/check_gateway_slo.py` 校验网关SLO阈值策略。
- release-gate 通过 `scripts/check_gateway_perf_report.py` 校验网关性能报告门禁。
