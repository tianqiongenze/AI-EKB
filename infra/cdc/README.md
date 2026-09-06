# CDC Outbox Relay（Debezium Server → Pulsar）

评审 P1 路线项：以 log-based CDC 取代轮询式 relay，消除多实例轮询竞争与数据库轮询压力（对标 Debezium Outbox Event Router 最佳实践）。

## 架构

```
TiDB (binlog) → Debezium Server (MySqlConnector + EventRouter) → Pulsar persistent://group/control/outbox-cdc
```

- 控制面写业务数据与 `outbox_events` 同事务落库（既有 Outbox 模式不变）。
- Debezium Server 以 binlog 订阅 `ekb_control_plane.outbox_events`，EventRouter 将 `event_type` 作为路由键、`payload_json` 作为事件体直接投递 Pulsar。
- 轮询 relay（`/events/relay` 与后台任务）保留作为降级路径：CDC 停机时置 `EKB_RELAY_BACKGROUND_ENABLED=true` 兜底，二者靠事件幂等消费共存。

## 部署

1. 为 TiDB 建最小权限 CDC 账号（SELECT + RELOAD/SUPER 或 Binlog ACL），密码经 `EKB_TIDB_CDC_PASSWORD` 注入。
2. `debezium-server` 容器挂载 `debezium-server-tidb-outbox.json` 为应用配置，镜像：`quay.io/debezium/server`（≥2.7，含 pulsar sink 插件）。
3. 消费端按既有 Pulsar topic 契约（`contracts/pulsar-topics.yaml`）订阅，`event_type` 与 17 类契约事件一一对应。

## 验收口径

- 事件端到端时延：轮询（秒级）→ CDC（百毫秒级）。
- 双路径并行期间零重复消费（消费端幂等键）。
