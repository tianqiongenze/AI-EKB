# 需求追踪矩阵（两份架构文档 + 雅迪需求调研）

## 1. 功能需求映射

| 需求来源 | 需求摘要 | 当前实现/资产 |
|---|---|---|
| 雅迪需求PDF | 战略分析看板、风险预警、跨部门协作 | `docs/enterprise-delivery-blueprint.md` + 控制面事件审计链路 |
| 雅迪需求PDF | 研发流程标准化、版本控制、设计复用 | `services/java-kgraph` + `contracts/` 契约资产 |
| 架构文档1 | 三层架构（中心/区域/边缘） | `docs/global-deployment-and-dr.md` + `infra/kustomize` |
| 架构文档1 | TiDB + Pulsar + 多语言服务边界 | `src/enterprise_ekb/tidb_store.py`、`event_bus.py`、`services/*` |
| 架构文档2 | MCP与Agent生态治理 | `docs/mcp-agent-skills-harness-governance.md` |

## 2. 非功能需求映射

| 类别 | 目标 | 实现与验证 |
|---|---|---|
| 性能 | 百万并发、低延迟 | `src/enterprise_ekb/capacity.py` + `perf/k6/load-test.js` |
| 可用性 | 99.99% | HPA/PDB/多环境部署模板 |
| 安全 | 数据隔离、审计可追溯 | MCP策略校验 + 审计表 + Outbox事件留痕 |
| 可扩展性 | 多区域、多工厂扩展 | `kustomize overlays` + topic命名规范 |
| 可运维 | 监控与发布门禁 | Harness门禁 + CI流水线 |

## 3. 版本与依赖基线

- Python: 3.11（CI）
- Java: 21（CI）
- Go: 1.22（CI）
- TiDB: 7.5+（建议，支持TiCDC→Pulsar）
- Pulsar: 3.x+（建议）
