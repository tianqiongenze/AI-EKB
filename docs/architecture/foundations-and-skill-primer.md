# Foundations and Skill Primer

## 1. Technical Foundation Map

| Domain | Core Concepts | Why it matters in EKB |
|---|---|---|
| MCP Governance | tool allowlist, schema validation, policy enforcement, auditability | prevents unsafe/untracked tool execution |
| Agent Skills Lifecycle | registration, versioning, promotion, rollback | enables controlled capability evolution |
| Harness Gate | quality/safety/regression checks | blocks risky releases |
| Event-Driven Reliability | outbox, retries, dead-letter handling | avoids data/event inconsistency |
| Data Residency | tenant/region/plant isolation | compliance and sovereignty |
| Multi-language Specialization | Python orchestration, Java reasoning, Go low-latency | better fit per workload |

## 2. Middleware Foundation Notes

### TiDB

- Control-plane relational backbone
- Migration-driven schema governance

### Pulsar

- Event backbone for skill/audit/observability streams
- Topic naming and tenant namespace discipline

### Redis

- Hot-path cache for low-latency reads
- Pool and timeout tuning critical for tail latency

### Neo4j

- Graph-based reasoning and relation traversal
- Batch relation operations reduce overhead

### Milvus

- Semantic vector retrieval path
- Tunable top-k search and indexing strategies

## 3. Architecture Skill Points for Contributors

1. Understand control-plane APIs before changing policy paths
2. Treat audit/event paths as critical integrity assets
3. Keep sensitive values out of Git-tracked plain values files
4. Update docs/contracts with every architecture-affecting change
5. Verify with tests before proposing rollout changes

## 4. Suggested Learning Path for New Maintainers

1. Read `README.md` and `docs/architecture/README.md`
2. Study `docs/mcp-agent-skills-harness-governance.md`
3. Walk through sequence diagrams in `interaction-sequence-diagrams.md`
4. Run tests and local service startup
5. Review Helm/K8s deployment assets and env examples
