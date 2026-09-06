# Changelog

本项目遵循显式版本记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

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
