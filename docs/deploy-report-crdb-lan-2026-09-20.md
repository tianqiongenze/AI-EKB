# EKB CRDB 数据面迁移 — 真实测试与部署报告

> 日期：2026-09-20 ｜ 环境：LAN K8s 集群（10.167.2.175 master / 10.167.2.176 worker，Rancher，v1.28.2）
> 镜像：`10.100.135.132:5000/ekb-control-plane:0.3.1-crdb`（amd64，集群内 registry）
> 命名空间：`ekb-app`（独立），数据面复用 `infra` 命名空间中间件

## 1. 决策背景（参考 ESP ADR-24 模式）

参考 `~/claude-Projects/English-Study-Platform` 的 ADR-24（CRDB 成为主数据面、TiDB 下电）与 `crdb-multi-node-migration-plan.md`（175×2+176×1 三节点 Raft）。联网确认（CockroachLabs 官方）：CRDB 说 PG wire 协议；follower reads 用 `AS OF SYSTEM TIME follower_read_timestamp()`（now−4.8s 保证本地副本可服务）或 `with_max_staleness`。

本集群实际状态（探测）：`infra` ns 三节点 cockroachdb-a/b/c（v24.3.11 CCL），`cockroachdb` NodePort 30257（SQL）/30259（admin）。**注意：该集群为无 license 的 CCL 版，并发打开事务数有硬上限。**

## 2. 重构内容

- `src/enterprise_ekb/crdb_store.py`（新增 ~700 行）：`CockroachDBControlPlaneStore`（PG 方言：IDENTITY 主键/JSONB/TIMESTAMPTZ/ON CONFLICT 幂等 upsert + `xmax=0` 插入判定）
- follower-read 读路径：`SET TRANSACTION AS OF SYSTEM TIME follower_read_timestamp(), READ ONLY`（**真机验证的唯一可行形态**——语句级 AS OF 在事务复用时报 `inconsistent AS OF SYSTEM TIME`；见 §4 踩坑）
- 配置：`EKB_DB_DRIVER=crdb` + `EKB_CRDB_HOST/PORT/USER/PASSWORD/DATABASE/FOLLOWER_READS`
- SQLite/TiDB/CRDB 三驱动并存，契约不变

## 3. 部署拓扑

```
ekb-app ns: ekb-control-plane ×2 (Deployment, NodePort 30880, probe /readyz+/healthz,
            annotations prometheus scrape, EKB_RELAY_BACKGROUND_ENABLED=true, JSON 日志)
infra ns:   cockroachdb-a/b-c (3-node Raft, PG wire 26257)  ← EKB_CRDB_HOST=cockroachdb.infra.svc.cluster.local
            redis / pulsar-broker（可达性已验证,REACHABLE）
```

## 4. 真实踩坑与修复（最有价值的部分）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | `inconsistent AS OF SYSTEM TIME timestamp` 反复报错 | 语句级 `AS OF SYSTEM TIME` 在 psycopg2 事务复用时与已开事务时间戳冲突 | 读统一走 `SET TRANSACTION AS OF SYSTEM TIME follower_read_timestamp(), READ ONLY` 作为事务首语句 |
| 2 | 集群级 `No license installed. The maximum number of concurrently open transactions has been reached`，**全集群 SQL 被拒** | **事务泄漏**：psycopg2 的 SELECT 隐式开事务，读路径从不 commit；每请求泄漏 1 个打开事务，CCL 免费版并发事务上限极低（实测 ~7 即触顶）。对照实验：ekb 副本 scale→0 后 `sql_txns_open` 立即归零 | 全部读路径补 `_read_commit()`（0.3.1 镜像）；20 连发 40 请求后 `sql_txns_open=0` 验证 |
| 3 | follower-read `with_max_staleness` 报 unimplemented | CRDB v24.3 限制：bounded staleness 不支持多 range/索引连接查询 | 使用 `follower_read_timestamp()` 形态 |
| 4 | `SET SESSION autocommit` 在事务中报错 | claim 路径残留 `autocommit=False` 赋值 | 移除，改为显式 commit/rollback |

## 5. 测试结果（全部真机执行）

| # | 测试 | 结果 |
|---|---|---|
| T1 | Skill 注册→三级晋级→MCP invoke 策略允许 | ✅ `accepted:true reason:ok`（CRDB 写路径 + 策略缓存 epoch 失效） |
| T2 | 域能力 bootstrap→coverage | ✅ `inserted:36`，coverage **12/12 域全部 met**（ON CONFLICT 幂等 upsert） |
| T3 | 审计回查 | ✅（audits 走 follower-read 事务） |
| T4 | 事务泄漏检查（40 请求连发） | ✅ `sql_txns_open=0`（修复前卡 7） |
| T5 | 压测 2000 请求 / 50 并发（coverage 读） | ✅ **1275 rps，ok 2000/2000，p50=31ms p95=71ms p99=85ms**（单副本） |
| T6 | follower-read vs 强读时延（集群内 30 次） | ✅ follower 1.15ms / strong 0.89ms（LAN 单机房差异小；多区域场景收益才显著——如实记录） |
| T7 | infra 中间件可达 | ✅ redis REACHABLE / pulsar REACHABLE |
| T8 | 后台 relay 自动发布（flywheel 事件） | ✅ outbox `published:11, pending:0, dead:0`，`ekb_outbox_relay_runs_total=2889` |
| T9 | 双副本原子认领 | ✅ 两 pod 并存，published 递增、无重复无 dead |
| T10 | 混合检索端到端 | ✅ lexical 腿命中 3 项（vector/graph 未接外部客户端，degraded=true 如实标记） |
| T11 | /metrics 指标族 | ✅ 28 个 ekb_* 指标 |
| T12 | 可观测响应头 | ✅ `x-request-id` + `traceparent`（W3C）+ `etag`（304 支持） |

本地回归：**91/91 Python 测试 + 四道门禁**全绿；镜像 0.3.0→0.3.1（泄漏修复）。

## 6. 遗留与建议

1. **CRDB license**：当前 CCL 免费版并发事务上限低，生产/压测上量前需评估 license 或限制连接并发（本报告 §4-2 的泄漏修复是前置必要条件，已具备）。
2. Pulsar 发布后端未在集群内启用（`InMemoryPublisher` 降级中，readyz 的 mismatch 检查仅在 `EKB_ENV=production` 生效）——下一步接 `pulsar://pulsar-broker.infra.svc.cluster.local:6650`。
3. Milvus/Neo4j（vector/graph 腿）未接入该集群，混合检索当前仅 lexical 腿真实生效。
4. 压测为单副本读路径；写路径与多副本扩展压测待 license 就绪后补。
