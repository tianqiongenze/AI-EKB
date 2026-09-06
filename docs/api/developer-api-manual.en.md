# Developer API Manual (English)

## 1. Platform Overview

Yadea EKB control plane provides skill governance, MCP invocation governance, A2A messaging, graph/vector operations, and auditable event-driven workflows.

## 2. Python Modules and Runtime Functions (Complete)

### `src/enterprise_ekb/app.py`
- `create_app(db_path=None)`: Builds and wires the FastAPI application and dependencies.
- `healthz()`: Liveness endpoint.
- `readyz()`: Readiness endpoint with storage/outbox status.
- `register_skill(...)`: Registers a skill and emits lifecycle events.
- `promote_skill(...)`: Promotes a skill stage and emits events.
- `mcp_invoke(...)`: MCP invoke path with auth, rate limit, policy, and audit.
- `evaluate_harness(...)`: Harness gate evaluation endpoint.
- `capacity_estimate(...)`: Capacity planning endpoint.
- `query_audit(...)`: Audit query endpoint.
- `relay_events(...)`: Outbox relay endpoint.
- `publish_a2a(...)`: A2A publish endpoint.
- `consume_a2a(...)`: Single-step A2A consume endpoint.
- `graph_upsert(...)`: Graph relation upsert endpoint.
- `vector_upsert(...)`: Vector upsert endpoint.
- `vector_search(...)`: Vector search endpoint.

### `src/enterprise_ekb/schemas.py`
- `SkillRiskLevel`, `SkillStage`: Skill enums.
- `SkillManifest`: Skill metadata model.
- `SkillPromotionRequest`: Promotion request model.
- `AuditQuery`: Audit query model.
- `GatewayInvokeRequest`: MCP invocation request model.
- `HarnessEvaluationRequest`, `HarnessEvaluationResult`: Harness models.
- `CapacityEstimateRequest`, `CapacityEstimateResult`: Capacity models.
- `RelayRequest`: Outbox relay model.
- `A2AEnvelope`: A2A envelope model.
- `GraphRelation`, `GraphUpsertRequest`: Graph request models.
- `VectorUpsertRequest`, `VectorSearchRequest`, `VectorSearchResult`: Vector models.

### `src/enterprise_ekb/a2a_runtime.py`
- `A2AConsumerConfig`: Consumer config.
- `A2ADispatcher.register(...)`: Register intent handler.
- `A2ADispatcher.dispatch(...)`: Dispatch by intent.
- `A2AConsumer.run_once()`: Consume one message and dispatch.
- `A2AConsumer.close()`: Release resources.
- `build_a2a_consumer(...)`: Build consumer with default handlers.

### `src/enterprise_ekb/config.py`
- `AppConfig`: Runtime config dataclass.
- `load_config()`: Environment-based config loader.

### `src/enterprise_ekb/rate_limiter.py`
- `RateLimitResult`: Limit check result.
- `TokenBucketRateLimiter.allow(...)`: Token-bucket limiter check.

### `src/enterprise_ekb/event_bus.py`
- `EventPublisher` protocol.
- `InMemoryPublisher`, `PulsarPublisher`.
- `OutboxRelay.run_once(...)`.

### `src/enterprise_ekb/middleware_clients.py`
- `RedisConfig`, `PulsarConfig`, `Neo4jConfig`, `MilvusConfig`.
- `HighPerformanceRedisClient`.
- `HighPerformanceNeo4jClient`.
- `HighPerformanceMilvusClient`.
- `HighPerformancePulsarClient`.

### Additional Python runtime modules
- `storage.py`: SQLite control-plane persistence.
- `tidb_store.py`: TiDB control-plane persistence.
- `migrator.py`: TiDB migration engine.
- `skill_registry.py`: Skill lifecycle manager.
- `capacity.py`: Capacity estimator.
- `harness.py`: Harness gate evaluator.
- `mcp_gateway.py`: MCP invocation gateway wrapper.
- `policy.py`: Policy evaluation engine.

## 3. Go Structs and Methods

### `services/go-gateway/main.go`
- `HealthResponse`
- `GatewayRuntimeConfig`
- Interfaces: `CacheAdapter`, `EventAdapter`, `GraphAdapter`, `VectorAdapter`
- `RedisCacheAdapter` and methods
- `PulsarEventAdapter` and methods
- `CircuitBreaker` and methods (`Allow`, `Report`)
- `GraphEdge`, `VectorHit`
- `Noop*` adapters
- `TokenBucketRateLimiter`
- `loadGatewayRuntimeConfig()`
- Middleware wrappers: `withGlobalRateLimit`, `withBackpressure`, `withTimeout`
- `executeWithRetry(...)`
- `chain(...)`
- `GatewayServer.routes()`
- `writeJSON(...)`
- `main()`
- gRPC capability adapters: `grpcCapabilityAdapter`, `CapabilityGatewayServiceClient`
- Metrics endpoint: `GET /metrics/gateway` (configurable)

## 4. Java Classes and Methods

### `services/java-kgraph/src/main/java/...`
- `KGraphApplication.main(...)`
- `KGraphController.healthz()`
- `KGraphController.reason(...)`
- `KGraphController.evaluatePolicy(...)`
- `KGraphController.aggregateInsights(...)`
- `KGraphController.governanceDecision(...)`
- `KGraphReasoningService.reason(...)`
- `KGraphReasoningService.fallbackReason(...)`
- `KGraphReasoningService.fetchFromGraph(...)`
- `KGraphReasoningService.evaluatePolicy(...)`
- `KGraphReasoningService.aggregateInsights(...)`
- `KGraphReasoningService.evaluateGovernanceGate(...)`

Additional Java capability endpoints:

- `POST /kgraph/policy/evaluate`
- `POST /kgraph/aggregate/insights`
- `POST /kgraph/governance/decision`

Java capability gRPC service:

- Service: `ekb.contracts.CapabilityGatewayService`
- RPCs: `EvaluatePolicy`, `AggregateInsights`, `GovernanceDecision`
- Port: `grpc.server.port` (default `9091`)
- Java stubs: generated from `contracts/proto/ekb_contracts.proto` during Maven build (`protobuf-maven-plugin`)

Compatibility bridge endpoints (debug/fallback only):

- `POST /grpc-bridge/capability/EvaluatePolicy`
- `POST /grpc-bridge/capability/AggregateInsights`
- `POST /grpc-bridge/capability/GovernanceDecision`

## 5. Control Plane API Endpoints

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

## 6. CI Runtime Validation

- Java runtime checks include Neo4j-backed integration test path.
- Go runtime checks include Pulsar path and limiter behavior.
- Release gate validates contract and bilingual document completeness.
- Release gate runs `pre-commit run --all-files`.
- Release gate enforces gateway SLO threshold policy via `scripts/check_gateway_slo.py`.
- Release gate enforces gateway performance report SLO via `scripts/check_gateway_perf_report.py`.
