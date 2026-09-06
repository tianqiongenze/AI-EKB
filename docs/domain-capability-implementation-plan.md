# 业务域能力设计与实施方案（完整落地版）

## 1. 目标

将雅迪需求稿中的业务域能力从“需求条目”落地为可执行、可审计、可持续扩展的工程能力。

覆盖域：

- strategy
- rnd
- manufacturing
- quality
- procurement
- aftersales
- hr
- finance
- materials
- marketing
- iot
- knowledge_graph

## 2. 统一能力模型

能力对象统一字段：

- `domain`
- `capability_type`
- `title`
- `description`
- `owner`
- `maturity`（planned/implemented/validated）
- `tags`
- `metadata`

## 3. API 落地

- `POST /domain/capabilities/upsert`：登记/更新业务域能力
- `POST /domain/capabilities/search`：按 domain/query 检索能力项
- `GET /domain/capabilities/coverage`：输出 met/partial/not_met 覆盖率
- `POST /domain/capabilities/bootstrap`：按需求基线初始化能力项

## 4. 存储与事件

### 4.1 存储

- 新增 `business_capabilities` 表
- 支持 domain + capability_type + title 的唯一约束
- 支持 TiDB/SQLite 一致能力

### 4.2 事件

- `domain.capability.upserted`
- `domain.capabilities.bootstrapped`

对应 Pulsar Topic：

- `persistent://group/control/domain-capability-upserted`
- `persistent://group/control/domain-capabilities-bootstrapped`

## 5. 覆盖率判定逻辑

- `met`：该域基线能力项全部存在
- `partial`：该域仅部分能力项存在
- `not_met`：该域基线能力项为 0

## 6. Outbox 升级策略（已实施）

- claim/processing（防多实例重复）
- topic 级批量发布（吞吐优化）
- 指数退避重试（稳定性优化）

## 7. 后续增强

1. 将能力项与具体工单/知识文档/图谱节点建立强关联
2. 引入 CDC Outbox（Debezium）降低轮询开销
3. 扩展为跨系统联动（ERP/MES/SCADA/工单/IM）可执行工作流
