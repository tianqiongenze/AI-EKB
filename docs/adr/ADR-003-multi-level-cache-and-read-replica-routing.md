# ADR-003: 多级缓存（L1/L2）与读写分离路由层

- 状态：accepted（2026-09）
- 背景：命中率 0%（wrapper 建而未接）；读查询全部走主库；查询与写入混跑。
- 决策：① `cache.MultiLevelCache`：L1 TTL+LRU + L2 Redis（故障降级），五腿接入（policy[epoch 失效]/域能力[前缀失效]/向量/audit[TTL]/capacity[纯函数]），命中率指标进 /metrics，supervision scan 有意排除（副作用）；② `ReplicaRoutingStore`：读方法路由副本（EKB_READ_REPLICA_DB_PATH / EKB_TIDB_READ_HOST），relay 保持主库。
- 后果：读扩展就绪（TiDB 副本接入即生效）；缓存陈旧度由 TTL/失效通道界定并有测试固化；schema 按上下文拆分与 testcontainers 为后续项。
