# 二期事件总线与SRE基线

## 1. 事件总线设计（Pulsar导向）

采用 Outbox + Relay 模式：

1. 业务事务先写本地数据库（skills/audits/harness_runs/outbox_events）
2. Relay 批量拉取 `pending` 事件
3. 发布到目标 Topic
4. 发布成功标记 `published`
5. 发布失败累加 `retries`，达到上限后标记 `dead`

## 2. 主题命名约定

- `persistent://group/control/skill-registered`
- `persistent://group/control/skill-promoted`
- `persistent://group/audit/mcp-invoke`
- `persistent://group/audit/harness-evaluated`
- `persistent://group/observability/capacity-estimated`

## 3. 重试与死信策略

- 单条事件最大重试：10 次
- `pending` -> `published` / `dead`
- `dead` 事件必须进入人工恢复或补偿流程

## 4. 运行保障指标

- Outbox pending 深度
- Relay 每批成功率
- Dead 事件数量与增长率
- 事件端到端时延

## 5. 与二期控制面集成点

- `/events/relay`：触发批量事件发布
- `/readyz`：返回 outbox 状态
- `/audit/query`：审计记录查询

## 6. 分布式 Outbox 升级（本仓库已实现）

为支撑多实例/高吞吐场景，Outbox 从“仅 pending 扫描”升级为：

1. 事件认领（claim）

- 新增字段：`claimed_by`、`claimed_at`
- Relay 拉取时先将事件标记为 `processing`，避免多实例重复消费
- 要求每个 Relay 实例具有唯一 `instance_id`（`EKB_RELAY_INSTANCE_ID`，默认 `HOSTNAME-pid`）

2. 批量发布

- 按 topic 聚合事件，调用批量发布接口
- 显著降低 broker 往返开销，提高吞吐

3. 指数退避重试

- 新增 `next_retry_at`
- 失败后按指数回退（上限 300s）重试，减少瞬时抖动放大

4. 处理超时回收

- 对已进入 `processing` 且超过 `next_retry_at` 的事件自动回收为 `pending`
- 解决实例崩溃导致的“永久 processing”卡死问题

4. 状态观测

- outbox 统计新增 `processing` 维度
- 与 pending/dead 联合形成运行态监控闭环

## 7. Outbox 适用边界说明

- Outbox 适用于“业务事务与消息投递解耦”的可靠异步模式。
- Outbox 并不天然提供全局 exactly-once；生产中仍应配合消费者幂等键与去重策略。
- 当消息规模持续增长到数据库轮询瓶颈时，应评估 CDC Outbox（Debezium）路径。
