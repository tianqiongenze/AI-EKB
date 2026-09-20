# Changelog

本项目遵循显式版本记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased] — 2026-09-20 管理台入集群 + 人工测试指南（九轮）

### Added

- **管理台集群部署**：`ekb-admin`（nginx + /api 反代控制面，NodePort 30881，镜像 0.1.1）——LAN 浏览器全功能人工测试入口。
- **局域网人工测试操作指南**：`docs/ops/ekb-app-manual-test-guide.md`（阶段化手册：前置含 CCL 事务余量阻断项、<2 分钟冒烟、浏览器四页+大屏 13 项用例、TC-1~7 治理/事件/检索、观测验收、Go/No-Go 签收、故障处置表）。

### Fixed

- **ETag 副本稳定性**（执行自己的指南时发现）：readyz ETag 曾含 per-pod 字段致 If-None-Match 随机失效——ETag 改为对副本稳定字段计算（镜像 0.3.2）；304 判定按"内容合法跳变"语义修正（3 次 ≥2 次）。

### Test

- 91/91 + 四门禁；0.3.2 部署后冒烟/304/指标实测通过。综合 7.8 → **8.0**。

## [Unreleased] — 2026-09-20 CRDB 数据面真机部署（八轮）

### Added

- **CRDB 数据面**（ADR-005，对齐 ESP ADR-24）：`crdb_store.py`（PG 方言 + follower-read SET TRANSACTION 形态 + ON CONFLICT 幂等），`EKB_DB_DRIVER=crdb`；LAN 集群（10.167.2.175/176）`ekb-app` 命名空间双副本部署（镜像 0.3.1-crdb）。
- **真实测试与部署报告**：`docs/deploy-report-crdb-lan-2026-09-20.md`（T1-T12：功能链路/1275rps 压测/双副本原子认领/follower-read/事务泄漏根因与修复）。

### Fixed

- **CRDB 事务泄漏**（真实事故）：psycopg2 读路径隐式事务不 commit，CCL 无 license 版并发事务上限触顶致全集群 SQL 拒绝——读路径补 `_read_commit()`，40 请求连发后 `sql_txns_open=0` 验证。

### Test

- 本地 91/91 + 四门禁；真机 T1-T12 全过。综合 7.5 → **7.8**。

## [Unreleased] — 2026-09-07 七轮：W3C trace 传播

### Added

- W3C trace context：上游 `traceparent` 保留（32 位 trace_id 端到端贯穿）、缺失时派生合法 traceparent；随 `X-Request-ID` 一同回写响应头。
- 评审 §21：通往 9.5-10 的分段实证路径（压测/生产运行/认证审计三段，明确不可在本环境生成项）。

### Test

- 基线 87 → **88 项**全绿（trace 传播 ×2 断言）；综合 7.4 → **7.5**（代码侧可完成项已基本清偿）。

## [Unreleased] — 2026-09-07 读写分离/消费幂等/ETag + ADR 档案

### Added

- **读写分离**：`ReplicaRoutingStore` 读方法路由副本（SQLite 同文件 / TiDB 副本经 `EKB_TIDB_READ_HOST`），relay 保持主库；未配置零行为变化。
- **A2A 消费幂等**：dispatcher 按 message_id 去重（600s 窗口），at-least-once 投递有效单次处理，duplicates 计数。
- **HTTP 缓存**：/readyz 与 /metrics 支持 ETag/If-None-Match→304；/metrics 豁免自观测（消除自引用棘轮）。
- **TOGAF ADR 档案**：`docs/adr/` ADR-001~004。

### Test

- 基线 83 → **87 项**全绿（路由拆分/同文件双库/重投递/304 ×2 端点）；四门禁通过；综合 7.3 → **7.4**。

## [Unreleased] — 2026-09-07 前端多端并行落地

### Added

- **M2 移动端骨架** `web/mobile/`：uni-app Vue3 基座（健康/容量两页、鸿蒙配置骨架、API 客户端与管理台对齐、设计令牌 SCSS 同源翻译 18/18）。
- **i18n**：自研轻量 t()（类型安全/localStorage/插值），zh-CN + en 双包（漏译编译报错），语言切换按钮，5 项测试。
- **车间大屏**：`WorkshopScreen`（内联 SVG 甜甜圈/条形图，零新增依赖），接入第 5 页签（i18n 同步）。
- **E2E + Lighthouse CI**：`e2e/` Playwright 冒烟（渲染/导航/主题/后端健康检查）+ GitHub Actions（chromium → E2E → Lighthouse 断言 → gzip<200KB 硬门禁）。

### Test

- 前端 8/8 组件测试 + 构建通过（gzip 49.9KB）；Python 79/79 + 四门禁维持全绿。

## [Unreleased] — 2026-09-07 四轮评审 + 缓存腿接入

### Security

- `POST /capacity/estimate` 补 Bearer 鉴权（原完全未授权即可调用并写事件；token 未配置时行为不变）。

### Added

- 缓存第四/五腿：audit query（TTL 30s，追加型日志）与 capacity estimate（TTL 3600s，纯函数哈希）——supervision scan 有意排除（副作用语义）。
- 检索层：加权 RRF（`weights`）+ 重排钩子（`reranker`），对标 2026 RRF 生产默认实证。
- 国标合规矩阵（GB/T 25000.51-2016 八特性逐项评估，评审 §18.2）。

### Test

- 基线 79 → **83 项**全绿（鉴权/缓存命中指标/加权 RRF 4 项）；四门禁通过；综合评分 7.2 → **7.3**。

## [Unreleased] — 2026-09-07 三轮评审 + 前端 M1.5

### 评审

- 新增三轮评审（§17）：项目群综合 **7.2/10**（四轮演进 6.1→6.5→6.9→7.0→7.2）；十维度证据化更新；风控复核 6.0（服务间达标，用户侧待 M2 账号体系）；命中率提升空间量化（audit/capacity/scan 三路径接入可再 +15-25pp）；GraphQL 复核结论：**未引入且维持不引入**（量化理由不变，P2 触发条件明确）。
- 联网对标：RRF 为生产默认融合（hybrid NDCG +26-31%，GraphRAG 多跳 86% vs 32%）——验证本项目 RRF 选型，加权 RRF + 重排器钩子列为检索层下一步。

### Changed（前端 M1.5，大厂标准）

- `web/admin`：组件化抽取（Card/StatusDot/JsonView）、暗色主题令牌（`[data-theme="dark"]`，同令牌契约）、主题切换、vitest+RTL 组件测试 3 项、tsc strict 构建门禁维持（gzip 48KB）。

### Test

- Python 79/79 + Java 11/11 + 前端组件 3/3 + 四道门禁全绿。

## [Unreleased] — 2026-09-07 后续待办清偿（专项 E 组）

### Added

- **OutboxRelay 后台任务化**：Litestar lifespan 异步循环（`EKB_RELAY_BACKGROUND_ENABLED` / `EKB_RELAY_INTERVAL_SECONDS`），免手动 /events/relay；原子认领保证多副本安全；relay 运行/发布/失败指标进 /metrics。
- **混合检索融合层**：`retrieval.py`（RRF k=60）+ `POST /retrieval/hybrid`（契约登记）——lexical（域能力目录）/ vector（Milvus）/ graph（可插拔钩子）三腿，不可用腿降级不失败。
- **CDC Outbox 资产**：`infra/cdc/`（Debezium Server 配置：TiDB binlog → EventRouter → Pulsar + 部署/验收文档）。
- **前端 M1 管理台**：`web/admin/`（React18+Vite+TS + W3C DTCG 令牌），四页：运行健康/容量估算/Skill 三级晋级/审计查询；构建通过（gzip 47.6KB）。
- `tests/conftest.py`：autouse 环境快照还原，根治测试间 env 泄漏。

### Changed

- **Java KGraph 去 mock**：Neo4j 不可用/空结果不再返回编造知识（设备/故障/点检），改为 `degraded:*` 显式降级标记；Java 11/11 测试通过。

### Test

- 基线 72 → **79 项**全绿（后台 relay 2 项 + 混合检索 5 项）；四道门禁通过。

## [Unreleased] — 2026-09 多级缓存 + create_app 拆分（专项 B/C/D）

### Added

- **多级缓存**（评审 §10.1 落地）：`cache.MultiLevelCache`（L1 TTL+LRU / L2 Redis，故障降级），接入策略判定（registry epoch 失效）、域能力 search/coverage（写路径前缀失效）、向量检索；命中率指标进 /metrics（`ekb_cache_hits_total` 等）。
- **create_app 拆分**（P1 结构欠账清偿）：app.py 1434 行 → 75 行装配层；36 个路由按限界上下文迁入 `api/` 包 10 个模块；共享依赖收敛为 `api/context.py`（`ControlPlaneContext` + `build_context`）；契约门禁扩展扫描 `api/*.py`。
- 4 项缓存测试（含策略晋级即时生效、域能力防陈旧读回归）。

### Fixed

- LIKE 通配符转义（SQLite/TiDB 双方言，`ESCAPE '\'`），封堵用户输入加宽匹配。
- 连接器硬编码假时间戳改为真实 UTC 时钟。
- 连接器 HTTP 客户端显式 `follow_redirects=False`（SSRF 纵深）。

### Test

- 基线 68 → **72 项**全绿；四道门禁通过；契约 36 路由 / 17 事件继续强制对齐。

## [Unreleased] — 2026-09 P0 风控与可靠性加固

### Security

- **防重放**：新增 `risk_control.AntiReplayMiddleware`（纯 ASGI）——HMAC-SHA256 请求签名（method+path+timestamp+nonce+body 摘要）、±300s 时间窗、Redis/内存单次 nonce 去重；`EKB_REQUEST_SIGNING_SECRET` 配置即启用，默认关闭零开销。
- **JWT 认证**：`verify_bearer_credential` 统一 admin/connector/业务三条鉴权路径——静态 Token 常量时比较 + HS256 JWT（exp 必验、aud 可选），静态 Token 向后兼容。
- **凭据整改**（P0-5）：neo4j 明文凭据改 secretKeyRef；redis `--requirepass` 注入；pulsar-standalone 启用 token 认证；milvus 启用 authorizationEnabled、minio 双键 secret 化；新增 `credentials-secret.example.yaml` 模板。

### Added

- **分布式限流**（P0-2a）：`DistributedRateLimiter`——Redis Lua 原子滑动窗口，故障自动降级内存滑窗；MCP/A2A 五个热点端点接入两级限流（`EKB_RATE_LIMIT_BACKEND=redis` 启用）。
- **结构化日志**（P0-6）：`logging_setup`——`EKB_LOG_FORMAT=json` 输出含 request_id 的 JSON 日志；ASGI 中间件生成 request_id 并回写 `X-Request-ID`；新增 Prometheus ServiceMonitor 清单。
- 新配置项：`EKB_RATE_LIMIT_BACKEND` / `EKB_REQUEST_SIGNING_SECRET` / `EKB_REPLAY_WINDOW_SECONDS` / `EKB_JWT_HS256_SECRET` / `EKB_JWT_EXPECTED_AUDIENCE` / `EKB_LOG_FORMAT`（env.*.example 同步）。

### Fixed

- **Outbox 原子认领**（P0-3）：SQLite store 与 TiDB store 对齐为单条原子 UPDATE，删除进程内锁依赖，多实例 relay 不再可能重复认领。
- 修复既有测试环境变量泄漏（`test_config_and_tidb_selection` 裸 `os.environ` 污染下游用例），受影响测试改为显式自设白名单。

### Test

- 测试基线：62 → **68 项**全绿；四道门禁持续通过。风控专项 6 项新测试（签名缺失/过期/坏签名/重放/放行、JWT 有效/过期/错 aud、分布式限流突发拒绝与降级）。

## [Unreleased] — 2026-09 框架迁移：FastAPI → Litestar + Granian

### Changed（Breaking / 框架级）

- **Web 框架整体迁移**：控制面从 FastAPI 迁移至 **Litestar 2.24**（全异步 ASGI 架构），服务器从 uvicorn 替换为 **Granian**（Rust 增强多 worker HTTP 服务器）。
  - 全部 36 个路由迁移；`app.py` 去除 FastAPI 依赖，AST 解析零 `fastapi` 残留
  - 所有 handler 显式 `sync_to_thread=True`（不阻塞事件循环，为 P0 异步化铺路）
  - 请求体参数统一到 Litestar 保留名 `data:`，连接对象统一为 `request: Request`
  - POST 状态码契约保持 200（显式 `status_code=200`），路径参数迁移为 Litestar 类型化形态 `{task_id:str}`（契约门禁做 `{p:type}`→`{p}` 归一化）
  - 校验错误保持 422 语义（`ValidationException` 自定义 handler）
  - `pyproject.toml` 依赖替换：`fastapi/uvicorn` → `litestar<3`/`granian`；Dockerfile CMD → granian；README 快速启动命令同步
  - 契约一致性门禁扩展为**双风格识别**（FastAPI `@api.get` 与 Litestar `@get`）
  - `/metrics` 中间件改为**框架无关纯 ASGI 实现**（`metrics.HTTPMetricsMiddleware`，优先读 Litestar `scope["path_template"]`）
- 删除 README 中不存在的 `yadea_ekb.app` 启动命令（历史漂移）。

### Verified

- 62/62 测试通过（迁移后全量回归）；四道门禁（契约一致性 / Flink preflight / replay SLO / gateway SLO）全部通过。
- Granian 真机冒烟：`/healthz` 200、`/metrics` 正常输出。

## [Unreleased] — 2026-09 架构评审与加固

### 评审

- 新增权威架构评审报告 `docs/architecture-review-2026-09.md`：10 维度加权打分（综合 6.1/10）、file:line 级证据、业界最佳实践对标（混合检索 / MCP OAuth2.1 / Outbox-CDC / FastAPI 生产实践）、P0/P1/P2 重构路线图。

### Fixed

- `infra/k8s/base/deployment-ekb-control-plane.yaml`：readinessProbe 由 `/healthz` 修正为 `/readyz`，与 Helm 模板对齐（此前就绪探针不检查依赖就绪）。
- `scripts/check_replay_e2e_slo.py`、`scripts/check_gateway_slo.py`：SLO 阈值解析加固，容忍 `p(90)` 等额外分位数与任意顺序（此前因脆弱正则误报失败）。
- `src/enterprise_ekb/app.py`：`_dump_alert` 双定义合并为模块级单实现。

### Security

- Bearer Token 比较统一改为 `secrets.compare_digest` 常量时比较；`app.py` 中 8 处内联校验收敛为 `_bearer_matches` 单点 helper（三种鉴权语义保持不变）。
- `EKB_AUTH_TOKEN` 缺省且非 production 环境放行时，输出显式 warning 日志（此前静默）。
- Pulsar/Milvus/Neo4j 客户端初始化失败的静默降级（`except: pass` 类）补 warning 日志（含异常栈）。

### Added

- 新增零依赖 Prometheus 指标模块 `src/enterprise_ekb/metrics.py` 与 `GET /metrics` 端点：
  - 全局 HTTP 中间件：`ekb_http_request_duration_seconds`（summary，路由模板级标签，404 归一为 `unmatched` 防基数爆炸）
  - Outbox 状态 gauge：`ekb_outbox_events{state=pending|processing|published|dead}`
  - OpenAPI 契约同步登记 `/metrics`
- 新增测试 `tests/test_metrics_and_auth_hardening.py`（5 项：指标格式、404 标签归一、401/200 鉴权语义、生产 fail-closed 保持）。
- 仓库根新增 `CHANGELOG.md`。

### Test

- 测试基线：57 → 62 项，全部通过；四道工程门禁（契约一致性 / Flink preflight / replay SLO / gateway SLO）全部通过。

### Roadmap

- P0（0-3 个月）：异步化热路径、Redis 分布式限流、Outbox 原子认领、OAuth2.1/JWT 升级、deps 凭据整改、可观测三件套。详见评审报告 §4。
