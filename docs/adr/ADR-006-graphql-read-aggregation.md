# ADR-006: 引入 GraphQL 读聚合层（strawberry.federation v2），写路径保留 REST

- 状态：accepted（2026-09-21）
- 参考：ESP 项目 writing-coach 服务（strawberry.federation + make_graphql_controller 模式）；GraphQL 生产加固清单（深度/复杂度限制、persisted queries、分页强制、内省控制）；Martin Fowler 多级缓存失效模式。

## 背景

前端多端（admin/移动端/车间大屏）存在"单页多实体"读取场景：文档详情+分块+审计、KPI 面板聚合。
REST 需多次往返且各端重复拼装；同时集团 30+ 基地规模下，多端差异化字段需求增多（over-fetching）。

## 决策

1. **GraphQL 定位为读聚合层**（strawberry.federation v2 subgraph，`/graphql`）：
   - 6 Query：documents / document / chunks / audits / rbacRoles / kpiPanel；1 Mutation：clearSemanticCache。
   - 写路径（ingest/delete/promote/assign）**仍走 REST**：事务语义、transactional outbox（EER）、审计绑定在 REST handler，
     GraphQL mutation 不进入治理链路——治理优先于便利。
2. **降级两层**（对齐 ESP esp-graphql-py）：resolver 内失败→返空列表/null + errors（不 panic）；
   REST 端点始终可用作 fallback（DPC 降级语义）。
3. **防复杂度攻击**：limit 钳制 1..100（0.7.0）；深度限制/cursor 分页/persisted queries 排 0.7.2（联网核实清单）。
4. **鉴权**：/graphql 挂在 AntiReplayMiddleware 之后；resolver 经 context.ctx 复用 REST 同款
   `_require_auth`/`_require_rbac_layer`（0.7.1 起 RBAC 服务级 token 直通、用户级凭据走 12 角色×4 层判定）。

## 压测证据（187 万 audits 真实数据，docs/bench/*.json）

| 场景 | REST p50 | GraphQL p50 | GraphQL 错误率 | REST 错误率（c=8） |
|---|---|---|---|---|
| S2 详情+chunks（1 vs 2 往返） | 79.1ms | 48.8ms（**-38%**） | 0% | 67% |
| S3 KPI 聚合面板 | 537.7ms | 392.5ms（**-27%**） | 0% | 12% |
| S1 单资源列表 | 25.8ms | 26.0ms（持平） | 0% | 0% |

结论：**GraphQL 的价值在聚合面（-27%~-38%）与可靠性（0 错误）**，单资源无优势——与业界共识一致。

## 后果

- 正面：多端 N+1 请求消除；字段裁剪降低带宽；federation 为 0.8.0 多区域聚合检索铺路（每区域一个 subgraph）。
- 代价：新依赖 strawberry-graphql（0.327.7，ASV 实测 `Schema(query=...)` 默认 federation 2，无 `enable_federation_2` 参数）；
  双协议契约维护成本（OpenAPI+GraphQL SDL），契约一致性测试扩展至 SDL（0.7.2）。
- 压测逼出 liveness probe timeoutSeconds=1 在负载下误杀 pod（restart 循环）→ 修为 5s/failureThreshold 6，
  已回写 `infra/k8s/base/deployment-ekb-control-plane.yaml` 与 Helm template（DGO）。
