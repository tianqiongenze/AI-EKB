# Runtime Architecture

## 1. Runtime Planes

### Control Plane Runtime (Python)

- Policy checks for MCP calls
- Skill lifecycle operations
- Harness gate execution
- Audit persistence and query
- Outbox relay trigger

### Data/Reasoning Runtime (Java + middleware)

- Graph reasoning requests
- Sentinel fallback path when risk/timeout threshold is exceeded
- Complex policy evaluation
- Complex aggregation and governance decisioning

### Gateway Runtime (Go)

- Low-latency request entrance
- AuthZ check and route dispatch
- Adapter-based middleware calls (cache/event/graph/vector)
- Layered rate-limiting (global/authz/route)
- Bounded inflight backpressure (fast-fail on overload)
- Route-scoped circuit breakers and retry budget
- Capability offload via gRPC + protobuf contract path (Java gRPC server on `grpc.server.port`, default 9091)
- Gateway metrics endpoint for canary/degrade/circuit observability

Runtime split rule:

- Go edge gateway remains a thin data-plane waist.
- Complex decision logic is delegated to Java capability services.

## 2. Runtime Resilience Patterns

- Bounded request timeouts on gateway paths
- Controlled fallback responses in Java reasoning service
- Publish retry/dead-event pattern in outbox relay
- Memory publisher fallback option in non-Pulsar environments
- A2A envelope publishing via Pulsar topics
- Gateway retry with bounded backoff to avoid retry storms
- Circuit breaker open/half-open transitions for dependency protection

## 3. Runtime Scaling Controls

- Horizontal scaling via HPA
- Min-availability via PDB
- Connection pool tuning via environment variables
- Inflight budget and per-route limiter budgets via gateway env controls

## 4. Observability and Audit Runtime

- Health endpoints (`/healthz`, `/readyz`)
- Capacity estimation endpoint for planning support
- Audit query endpoint and event records
- Event topics for governance and operational traces

## 5. Runtime Performance Baselines

Reference SLO budgets in `docs/phase3-hardening-architecture.md`:

- Go gateway P99 target: low-latency budgeted
- Python control-plane P99 target: governance + persistence budgeted
- Java KGraph reasoning P99 target: bounded with degrade path

Gateway SLO thresholds are policy-gated in CI via `scripts/check_gateway_slo.py` against `perf/k6/load-test.js`.
