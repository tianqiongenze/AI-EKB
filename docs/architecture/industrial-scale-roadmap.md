# Industrial-Scale Runtime Roadmap (10B Users / 10M Concurrent)

## 1. Hard Constraints & Targets

- Total users: 10B
- Concurrent sessions: 10M
- Multi-region + multi-plant isolation
- Zero-trust governance & auditable tool invocation

## 2. Near-Term (P0) — Achievable in 1–2 quarters

1. **Control/Data Plane separation**
   - Control plane handles skill/policy/harness/audit only
   - Runtime invocation handled by gateway + event backbone

2. **A2A v1 runtime**
   - Use `contracts/a2a-protocol.yaml`
   - Pulsar topics per tenant/region/agent
   - Idempotency and DLQ enforcement

3. **Gateway productionization**
   - Redis cache + rate limiting
   - AuthZ and route decisions cached
   - Publish runtime audits to Pulsar

## 3. Mid-Term (P1) — Industrial scale

1. **Shard by tenant/region**
   - Pulsar namespace partitioning
   - TiDB partitioning + audit archival
   - Redis cluster per region

2. **Observability baseline**
   - Trace/correlation ID propagation
   - Metrics for MCP/A2A latency and error rates

3. **Data-plane services**
   - Java KGraph + Neo4j query integration
   - Milvus query path integrated into routing

## 4. Long-Term (P2) — Planet scale

1. **Multi-plane control**
   - Global policy plane + regional control plane
   - Dynamic policy distribution via Pulsar

2. **Session routing fabric**
   - A2A orchestration layer (planner/specialist/verifier)
   - Backpressure-aware routing and load shedding

3. **Compliance & audit expansion**
   - Regulatory export pipelines
   - Immutable audit storage for long retention
