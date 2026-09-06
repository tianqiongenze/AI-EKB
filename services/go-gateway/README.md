# Go Gateway Service

该模块对应架构中的 Go 高性能服务职责：

- Dialogue 路由
- AuthZ 检查（Casbin兼容边界）
- 低时延网关扩展
- Redis/Pulsar/图谱/向量中间件访问适配层（高性能访问接口）

## Phase-3-3 中间件访问策略

- `CacheAdapter`：批量读写与TTL策略（适配 Redis pipeline/mget）
- `EventAdapter`：批量发布（适配 Pulsar batching）
- `GraphAdapter`：关系批量写入（适配图数据库批处理）
- `VectorAdapter`：低延迟TopK查询（适配向量数据库）

当前默认提供 `Noop*Adapter`，用于本地无依赖运行与测试；生产环境可通过相同接口替换为真实客户端实现。

## Gateway 极致化运行时能力

当前网关已内建以下运行时保护机制：

- 分层限流：global / authz / route
- 租户+路由动态配额：`tenant|route` 粒度
- 有界并发背压：超过 `EKB_GATEWAY_MAX_INFLIGHT` 时快速返回 `gateway_overloaded`
- 路由级超时预算：authz 与 route 使用独立超时窗口
- 外部调用重试：事件/图谱写入等关键外部调用支持重试+退避
- 熔断器：authz 与 route 路径独立熔断（closed/open/half-open）
- 流量整形：一致性哈希 canary 分流（租户稳定）
- 退化控制：基于错误预算触发短时降级窗口
- TLS 终止：支持通过证书环境变量直接启用 HTTPS 监听
- Capability 调用：优先 gRPC + protobuf 契约，HTTP JSON 仅回退路径
- 灰度与稳态观测：内建指标导出端点（canary、degrade、circuit states）

## 关键环境变量（Go Gateway）

- `EKB_GATEWAY_GLOBAL_RATE_LIMIT_PER_MINUTE`
- `EKB_GATEWAY_AUTHZ_RATE_LIMIT_PER_MINUTE`
- `EKB_GATEWAY_ROUTE_RATE_LIMIT_PER_MINUTE`
- `EKB_GATEWAY_AUTHZ_TIMEOUT_MS`
- `EKB_GATEWAY_ROUTE_TIMEOUT_MS`
- `EKB_GATEWAY_RETRY_MAX_ATTEMPTS`
- `EKB_GATEWAY_RETRY_BACKOFF_MS`
- `EKB_GATEWAY_MAX_INFLIGHT`
- `EKB_GATEWAY_CIRCUIT_BREAKER_FAILURE_THRESHOLD`
- `EKB_GATEWAY_CIRCUIT_BREAKER_OPEN_SECONDS`
- `EKB_GATEWAY_CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS`
- `EKB_GATEWAY_CANARY_PERCENT`
- `EKB_GATEWAY_PRIMARY_ROUTE`
- `EKB_GATEWAY_CANARY_ROUTE`
- `EKB_GATEWAY_TENANT_ROUTE_LIMITS_RELOAD_SECONDS`
- `EKB_GATEWAY_TENANT_ROUTE_LIMITS_JSON`
- `EKB_GATEWAY_DEGRADE_ERROR_RATE_PERCENT`
- `EKB_GATEWAY_DEGRADE_WINDOW_SECONDS`
- `EKB_GATEWAY_DEGRADE_DURATION_SECONDS`
- `EKB_GATEWAY_DEGRADE_MIN_SAMPLES`
- `EKB_GATEWAY_GRAPH_UPSERT_URL`
- `EKB_GATEWAY_VECTOR_SEARCH_URL`
- `EKB_GATEWAY_CAPABILITY_SERVICE_URL`
- `EKB_GATEWAY_CAPABILITY_GRPC_ADDRESS`
- `EKB_GATEWAY_CAPABILITY_GRPC_TIMEOUT_MS`
- `EKB_GATEWAY_METRICS_PATH`
- `EKB_GATEWAY_AUTH_TOKEN`
- `EKB_GATEWAY_TLS_CERT_FILE`
- `EKB_GATEWAY_TLS_KEY_FILE`

## 分层架构执行原则

- Go Edge Gateway 仅保留数据平面逻辑：TLS、鉴权、限流、路由、超时、重试预算、熔断、流量整形、快速失败。
- 复杂策略评估、图谱/规则推理、复杂聚合、治理决策全部下沉到 Java 能力层，通过接口调用完成。
- 网关禁止引入重业务逻辑，确保热路径可预测与低延迟。

## SLO 门禁

`release-gate` 会执行：

- `python scripts/check_gateway_slo.py`
- `python scripts/check_gateway_perf_report.py`

该脚本会校验 `perf/k6/load-test.js` 中 gateway 延迟阈值不劣化于策略上限（默认 p95≤250ms, p99≤500ms）。
并校验 `perf/reports/gateway-latest-summary.json` 中最近性能报告是否满足错误率与延迟门限。

## gRPC Capability 契约

- 公共契约文件：`contracts/proto/ekb_contracts.proto`
- Go 侧镜像契约文件：`services/go-gateway/capability_grpc.proto`
- gRPC service：`ekb.contracts.CapabilityGatewayService`
- 方法：
  - `EvaluatePolicy`（`google.protobuf.Struct -> google.protobuf.Struct`）
  - `AggregateInsights`（`google.protobuf.Struct -> google.protobuf.Struct`）
  - `GovernanceDecision`（`google.protobuf.Struct -> google.protobuf.Struct`）

优先通过 `EKB_GATEWAY_CAPABILITY_GRPC_ADDRESS` 启用 gRPC；如不可用，可回退 `EKB_GATEWAY_CAPABILITY_SERVICE_URL`（HTTP JSON）。

Java 服务端默认监听 `grpc.server.port=9091`，服务名为 `ekb.contracts.CapabilityGatewayService`。

## 观测指标导出

通过 `EKB_GATEWAY_METRICS_PATH`（默认 `/metrics/gateway`）提供 JSON 指标：

- `gateway_canary_hits`
- `gateway_primary_hits`
- `gateway_degrade_hits`
- `gateway_authz_circuit_open_hits`
- `gateway_route_circuit_open_hits`
- `gateway_authz_circuit_state_code`
- `gateway_route_circuit_state_code`
- `gateway_capability_mode`（`grpc`/`http-json`/`noop`）

其中关键可观测项覆盖：

- canary 命中率：`gateway_canary_hit_ratio`
- 降级触发率（可由 hits/请求量计算）：`gateway_degrade_hits`
- 熔断状态指标：`gateway_authz_circuit_state_code`、`gateway_route_circuit_state_code`

## Go Edge + Java Capability 分层落地

当前 Go 网关在 `/v1/dialogue/route` 可对接 Java 能力层：

- gRPC 主路径：`ekb.contracts.CapabilityGatewayService/*`
- HTTP JSON 回退路径：
  - `/kgraph/policy/evaluate`
  - `/kgraph/aggregate/insights`
  - `/kgraph/governance/decision`

网关只调用能力层结果，不承载复杂推理与治理逻辑，保持热路径简洁。

## 本地运行

```bash
go run .
```

默认端口：`8090`

## 测试

```bash
go test ./...
```
