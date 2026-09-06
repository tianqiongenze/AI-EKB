# Cross-Region Replication Pack

This directory provides implementation-oriented replication scaffolding for production evolution:

- `tidb/ticdc-changefeed.yaml`: TiCDC changefeed policy template
- `redis/redis-replication-policy.yaml`: Redis replication guard rails
- `neo4j/neo4j-causal-cluster-values.yaml`: Neo4j causal cluster reference values
- `milvus/milvus-backup-sync-cronjob.yaml`: Milvus snapshot sync job template
- `pulsar/pulsar-geo-replication-policy.yaml`: Pulsar geo-replication policy

## Rollout Order

1. TiDB changefeed
2. Pulsar geo-replication
3. Redis replication
4. Neo4j causal cluster
5. Milvus periodic backup-sync

## Operational Notes

- Validate replication lag metrics before global traffic cutover.
- Enforce per-domain data residency before enabling cross-region reads.
- Run quarterly disaster-recovery cutover drills for all stores.
