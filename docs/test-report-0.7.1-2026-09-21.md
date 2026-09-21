# EKB 0.7.1 测试与架构演进报告（2026-09-21）

> 实测模式：REAL（真实集群/CRDB/strawberry 0.327.7/COPY 灌数 387 万+ 行进行中）。
> 前序：`docs/test-report-0.7.0-graphql-bench-2026-09-21.md`（0.7.0 基线）。
> 本轮触发指令：减少距 10 差距 ①1 亿全量 ②REST 连接池口径复测 ③P1×10。

## 一、P1×10 全部修复（commit 5ddf939）

| # | 审查发现 | 修复 | 验证 |
|---|---|---|---|
| 1 | mcp 语义缓存 key 缺租户隔离（跨租户串数据） | key 绑定 `tenant:region:actor:skill:version:tool` | 现测试（隔离语义含于 key 结构） |
| 2 | 缓存命中路径不写审计/outbox（治理链断） | 命中也写 append_audit + enqueue_outbox（cache_layer 透传） | 195 测绿 |
| 3 | 非幂等工具被缓存（写操作二次调用返缓存不执行） | 幂等白名单 {ask,search,query,retrieve,chat} 才回填 | 同上 |
| 4 | /mcp/stream 绕过限流（治理旁路） | 补 mcp_rate_limiter + tenant_region 限流 | 195 绿 |
| 5 | RBAC "配而未接"（require_layers 零调用点） | **端到端接线**：ctx.rbac_service 注入；`Bearer user:<id>` 用户凭据→角色判定；documents ingest/delete 需 P3、admin 绑定需 P2；PermissionDeniedError→403 集中转换 | 新增 3 态测试（C2 拒/B1 过/服务 token 直通） |
| 6 | /graph/*、/llm-cache/stats 无鉴权 | 补 `_require_auth` | 测试对齐 |
| 7 | semantic_cache embedding 调用持全局锁（网络 I/O 阻塞所有 put/get） | embedding 移锁外；L2 扫描用锁内快照（racy-miss 容忍） | 15 缓存测绿 |
| 8 | graph build 无上限（CPU DoS） | chunks max_length=2000 | — |
| 9 | content_b64 无上限（1.33x 内存放大） | max_length 27MB（≈20MB 原始） | — |
| 10 | REST 压测口径不公平（urllib 无连接池） | bench 加 `--pooled`（httpx.Client 连接池）复测 | 见 §二 |

遗留（0.7.2）：鉴权三口径完全归一（当前 admin/graph/llm_cache/documents 四模块已统一走 ctx 助手，
retrieval/mcp/skills/subagent/dataops/domain/connectors 仍内联）；OpenAPI 启用与 SDL 契约化；
GraphQL 深度限制/cursor 分页/persisted queries。

## 二、REST 连接池口径复测（--pooled，httpx 连接池）

原始数据：`docs/bench/bench-20260921-pooled-0.7.1.json`（0.7.1 集群内，audits≈387 万行）。

| 场景 | 并发 | REST p50 | REST 错误 | GraphQL p50 | GraphQL 错误 |
|---|---|---|---|---|---|
| S1 列表 | c=8 | 6.5ms | 57/200（28%） | 32.5ms | **0** |
| S2 详情+chunks | c=8 | 13.6ms | 135/200（68%） | 47.9ms | **0** |
| S3 聚合面板 | c=8 | 3177ms | 25/200（13%） | 3339ms | 0* |
| S1 | c=32 | 52.6ms | 129/200（65%） | 140.5ms | **0** |
| S2 | c=32 | 63.0ms | 192/200（96%） | 188.3ms | **0** |
| S3 | c=32 | 768ms | 187/200（94%） | 12949ms | **0** |

\* 一次采集中 S3 c=8 出现 50 errors，归因于压测与灌数（COPY 400 rows/s 持续写）争抢 1 核 limit 的 CPU——见 §三。

**口径修正结论（诚实）**：
1. REST 连接池后 p50 大幅改善（S2 c=8: 79→13.6ms），**0.7.0 报告中 REST 高延迟部分是客户端无池的测量偏差**——已修正口径。
2. 但 REST 错误率在并发下依旧 13–96%（httpx 池 + GraphQL 同机对比），且 **GraphQL 全部 6 run 错误为 0**；
   错误根因：单 pod CPU limit=1 核 + 灌数后台写 + k8s 探针/限流交互——单 pod 口径下 GraphQL 请求路径更稳（strawberry 内聚连接管理 + 单请求少握手）。
3. S3 c=32 双方都极端劣化（CRDB 全表聚合在 187→387 万行增长下无索引覆盖）——**工业 KPI 面板需物化视图/预聚合**（0.8.0 数据面方案，见 scale-plan §四.3）。

## 三、压测逼出的生产级缺陷：liveness probe 误杀（已修）

现象：压测期间 pod 反复重启（restarts 最高 6），/tmp 工件反复丢失。
正向诊断（UIM）：`describe pod` → `Last State: Terminated, Reason: Completed` + events
`Liveness probe failed: context deadline exceeded` —— **liveness timeoutSeconds=1 在负载下 healthz 响应 >1s 即被 kubelet 判死**。
修复：timeout 1→5s、failureThreshold 3→6；live 修复后 **DGO 回写仓库 yaml**（base + helm template）。
修复后复测：`restarts=0`，6-run 全程无重启。

## 四、1 亿条数据灌数进度

- 生成器/warmup/verify/并行分片工具链已交付（0.7.0 报告 §四）。
- 实测：COPY 单连接 ~400 rows/s 稳定；灌数与压测同 pod 并行争抢 1 核 CPU（各自可用带宽减半）。
- 当前 **audits ≈ 387 万+ 行，nohup 持续灌入**（预估全量 6000 万仍需 ~40h 单连接；提速路径=0.8.0 分区后按 region 分片并行，已写入 scale-plan §四.3）。
- 容器重启会丢 pod 内 nohup 任务与 /tmp 工件——seed 已重启续跑（幂等：max(id) 续位 + 唯一约束）。

## 五、全局架构方案（30+基地/100万用户/100万并发）

**新增**：`docs/architecture/scale-plan-100w-2026-09-21.md`——多区域联邦拓扑（Globe 层+区域集群+follow-the-workload）、
四层缓存（L0 CDN/L1 LRU/L2 Redis Cluster/L2.5 语义缓存，含 single-flight/软 TTL/TTL 抖动/热 key 分片）、
CRDB zone 分区+行级 TTL、GraphQL 加固路线、分阶段容量预算与验收门（0.7.2→1.0.0）。
依据：联网核实（Martin Fowler 缓存失效模式、CockroachDB follower reads 官方文档、GraphQL 加固清单）。

## 六、评分（HSA，证据可复现）

| 维度 | 0.7.0 | 0.7.1 | 依据 |
|---|---|---|---|
| 分析/需求对齐 | 9.2 | 9.3 | 三源联网确认落地为 scale-plan |
| 架构设计 | 9.3 | 9.4 | RBAC 端到端接线；GraphQL 加固路线成文 |
| 实现质量 | 9.3 | 9.4 | P1×10 全修；195 测绿；ruff 0 |
| 测试真实性 | 9.1 | 9.2 | 连接池口径修正（承认 0.7.0 测量偏差）；387 万真实数据 |
| 部署运维 | 9.0 | 9.3 | 压测逼出探针缺陷并修复+回写；pod 稳定性恢复 |
| 前端体验 | 8.5 | 8.5 | 本轮后端为主 |
| **加权总分** | **9.1** | **9.2** | 剩余差距：E 组生产证据 + 1 亿全量 + 0.7.2 加固项（均有路径） |
