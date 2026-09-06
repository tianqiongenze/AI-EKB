# Production Evolution Pack (Multi-Cluster / Global Traffic / Replication / Tiered Capacity)

## 1. Scope

This pack upgrades the repository from two-region simulation to a production-oriented implementation baseline across four pillars:

1. Multi-cluster deployment topology and rollout workflow
2. Global traffic routing and failover policy
3. Cross-region data replication design + implementation manifests
4. Tiered capacity model and staged load-testing execution

## 2. Delivered Artifacts

### 2.1 Multi-Cluster + Global Traffic

- `infra/k8s/production-pack/multicluster/regions/region-a/control-plane-values.yaml`
- `infra/k8s/production-pack/multicluster/regions/region-b/control-plane-values.yaml`
- `infra/k8s/production-pack/global-traffic/gatewayclass.yaml`
- `infra/k8s/production-pack/global-traffic/http-route-weighted.yaml`
- `infra/k8s/production-pack/global-traffic/health-policy.yaml`
- `infra/k8s/production-pack/global-traffic/global-dns-record.yaml`
- `scripts/deploy_multicluster_global_pack.py`

### 2.2 Cross-Region Replication

- `infra/k8s/production-pack/replication/tidb/ticdc-changefeed.yaml`
- `infra/k8s/production-pack/replication/redis/redis-replication-policy.yaml`
- `infra/k8s/production-pack/replication/neo4j/neo4j-causal-cluster-values.yaml`
- `infra/k8s/production-pack/replication/milvus/milvus-backup-sync-cronjob.yaml`
- `infra/k8s/production-pack/replication/pulsar/pulsar-geo-replication-policy.yaml`
- `infra/k8s/production-pack/replication/README.md`

### 2.3 Capacity Model + Tiered Load

- `perf/tiered/tiers.yaml`
- `perf/k6/tiered-gateway-load.js`
- `scripts/run_tiered_capacity_loads.py`

## 3. Tiered Validation Strategy

`perf/tiered/tiers.yaml` defines 5 tiers from canary to stress-failover:

- `tier-0-canary`
- `tier-1-regional-baseline`
- `tier-2-regional-peak`
- `tier-3-multiregion-failover`
- `tier-4-global-stress-sim`

Each tier specifies:

- VUs / duration
- failover injection toggle
- target error-rate and p95/p99 objectives
- expected concurrency scale interpretation

`scripts/run_tiered_capacity_loads.py` executes these tiers and emits:

- `perf/reports/tiered-capacity-summary.json`
- per-tier k6 summaries under `perf/reports/tiered/`

## 4. Implementation Notes

1. This pack is production-oriented infra-as-code scaffolding; it is not a claim that global 10B-user capacity is already achieved.
2. Real global readiness still requires:
   - multi-cluster control plane in real cloud regions,
   - managed global DNS/GSLB integration,
   - continuous replication lag monitoring,
   - long-run soak and chaos drills.
3. Global readiness gaps are scored and prioritized in
   [`../architecture-review-2026-09.md`](../architecture-review-2026-09.md)
   (dimension 2/10: concurrency readiness 4.5/10; dimension 10: scale-target fit 4.0/10),
   whose P0 roadmap (async hot paths, distributed rate limiting, atomic outbox
   claiming, OAuth2.1/JWT, dependency credential hardening, observability stack)
   is the mandatory prerequisite before tier-3/tier-4 results can be treated as
   production evidence.

## 5. Rollout Sequence (Recommended)

1. Apply replication policies per datastore.
2. Deploy both regional clusters with region-specific Helm values.
3. Apply global traffic resources (Gateway API + DNS + health policy).
4. Run tier-0 → tier-4 staged load plan.
5. Compare tier outcomes against SLO budgets and tune resources/routes.
