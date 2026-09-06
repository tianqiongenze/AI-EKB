# Yadea EKB Platform Product Guide (English)

## 1. Product Overview

Yadea EKB is an industrial-grade AI knowledge platform for enterprise-scale manufacturing organizations, providing governance, collaboration, retrieval, and compliance-ready operations.

## 2. Functional Matrix (Detailed)

1. Skill lifecycle governance (register/review/staging/production)
2. MCP invocation governance (auth, rate limit, policy, audit)
3. A2A protocol orchestration (envelope, routing, consume/dispatch)
4. Graph capability (relation upsert)
5. Vector capability (upsert/search)
6. Event backbone (Pulsar) with Outbox consistency
7. Capacity estimation and harness-based release gates

## 3. Core Implementation Principles

### 3.1 MCP Execution Path
Request -> Authentication -> Rate limit -> Policy check -> Execution -> Audit persistence -> Event publication.

### 3.2 A2A Collaboration Path
Envelope publish -> Outbox -> Pulsar topic -> Consumer -> Dispatcher -> Intent handler.

### 3.3 Graph/Vector Retrieval Path
Graph writes use batch relation upserts via Neo4j; vector writes/searches use Milvus for retrieval augmentation.

## 4. Deployment and Operations

1. Multi-environment deployment via K8s/Helm/Kustomize
2. Bare-metal one-click deployment via Docker Compose script
3. Secret injection and environment-layered config model

## 5. Typical Business Scenarios

- R&D knowledge retrieval
- Manufacturing process optimization
- Quality anomaly analysis and traceability
- After-sales intelligent assistance

## 6. Industrial Roadmap

1. Next: business-grade A2A handlers, real Go Pulsar event path, deeper Java graph reasoning
2. Mid-term: multi-region active-active, full observability, compliance reporting
3. Long-term: global scheduling and autonomy for 10B users / 10M concurrency

## 7. Pre-release Acceptance Closure

- CI validates Python/Java/Go runtime paths.
- Integration services (Neo4j/Pulsar/Milvus) are wired in CI.
- Release gate enforces contracts and bilingual documentation presence.
