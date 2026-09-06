# Production Launch Checklist v1

## A. Multi-Environment Multi-Active Deployment

- [ ] dev region-a / region-b all deployments ready
- [ ] staging region-a / region-b all deployments ready
- [ ] prod region-a / region-b all deployments ready
- [ ] gateway route policy applied and health policy active

Evidence:

- `perf/reports/multi-env-multiactive-summary.json`

## B. Data Synchronization (Historical + Incremental)

- [ ] Existing 1M dataset synchronized to both regions
- [ ] New synthetic dataset synchronized to both regions
- [ ] TiDB / Redis / Neo4j / Milvus sync jobs completed without failure

Evidence:

- `perf/reports/multiregion-data-sync-summary.json`
- `perf/reports/sync-seed-region-a.log`
- `perf/reports/sync-seed-region-b.log`

## C. Production Parameterized Dry-Run

- [ ] Helm lint for control-plane and flink-jobs passed
- [ ] Helm template render passed with production parameters
- [ ] Kustomize production overlay client dry-run passed
- [ ] Contract / preflight / SLO / artifact checks passed

Evidence:

- `perf/reports/production-param-dryrun-summary.json`

## D. Gate Decision

- [ ] Go/No-Go decided by release owner
- [ ] Risk exceptions documented
- [ ] Rollback owner and runbook acknowledged
