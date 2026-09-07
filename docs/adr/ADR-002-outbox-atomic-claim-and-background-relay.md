# ADR-002: Outbox 原子认领 + 后台 relay 任务化

- 状态：accepted（2026-09）
- 背景：SELECT→UPDATE 两段式认领依赖进程内锁，多实例存在重复投递竞态；relay 依赖手动触发。
- 决策：单条原子 UPDATE（id IN 子查询 + status 守卫）对齐 SQLite/TiDB 两方言，删除进程内锁；Litestar lifespan 异步循环（EKB_RELAY_BACKGROUND_ENABLED，默认关）自动认领发布，配 relay 运行/发布/失败指标。
- 后果：多副本 relay 天然安全（原子认领）；CDC（Debezium，infra/cdc）为演进路径，轮询 relay 保留为降级路径。
