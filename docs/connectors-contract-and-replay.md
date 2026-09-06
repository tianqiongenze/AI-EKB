# ERP/MES/SCADA/工单连接器骨架：契约与回放

## 1. 目标

构建第一批真实 connector 骨架，统一接入契约、幂等处理与回放测试能力。

覆盖系统：

- ERP
- MES
- SCADA
- Ticketing

## 2. API

- `POST /connectors/ingest`
  - 输入：`ConnectorEnvelope`
  - 语义：统一接入外部系统事件，按 `idempotency_key` 去重
- `POST /connectors/replay`
  - 输入：`ConnectorReplayRequest`
  - 输出：`ConnectorReplayResult`
  - 语义：对已持久化 envelope 做回放验证

联调扩展 API：

- `POST /connectors/profiles/upsert`
  - 维护连接器配置（base_url/auth/timeout/pull_batch_size）
- `POST /connectors/profiles/list`
  - 查询可联调 profile
- `POST /connectors/checkpoint/get`
  - 读取增量游标
- `POST /connectors/checkpoint/update`
  - 更新增量游标
- `POST /connectors/health`
  - 执行 profile 就绪检查（URL/auth 状态）
- `POST /connectors/pull`
  - dry_run: 仅模拟拉取，不推进 checkpoint
  - commit: 拉取并 ingest，推进 checkpoint

## 3. 数据模型

`connector_envelopes` 关键字段：

- connector_system
- direction
- tenant_id / region_id / source_id
- event_type / occurred_at
- idempotency_key（与 connector_system 组成唯一键）
- payload_json / metadata_json
- status / replay_count / last_replayed_at

## 4. 回放与幂等

- 首次 ingest：`accepted`
- 相同 `(connector_system, idempotency_key)` 再次 ingest：`replayed`
- replay API：按系统筛选已持久化事件并重新 dispatch
- Connector 持久化 `status` 与 outbox 事件 `status` 保持一致
- 重复 ingest 会更新 replay 计数与最近回放时间（可审计）

## 5. 联调模式

### dry_run

- 产出模拟拉取结果与样本事件 ID
- 不写入 connector checkpoint

### commit

- 拉取后进入 ingest 流程
- 成功后推进 checkpoint（cursor）
- 记录 pull run 审计与 outbox 事件

## 6. 真实系统适配层（SAP / ServiceNow）

- SAP ERP（OData）适配器：建议在 profile.metadata 中配置 `endpoint` 与 delta token 处理字段。
- ServiceNow 适配器：建议在 profile.metadata 中配置 `table` 和 `sys_updated_on` 游标策略。
- `adapter_type` 用于选择具体适配器逻辑（默认 generic）。

建议的 profile 配置字段：

- SAP
  - `adapter_type`: `sap_odata`
  - `metadata.endpoint`: OData EntitySet 路径
  - `metadata.delta_field`: 变更时间字段（默认 `LastChangeDateTime`）
  - `metadata.delta_token`: 首次全量后保存的 deltalink/token
- ServiceNow
  - `adapter_type`: `servicenow_table`
  - `metadata.table`: 表名（默认 `incident`）
  - `metadata.delta_field`: `sys_updated_on`
  - `metadata.watermark`: 增量起点

认证与签名：

- `auth_type=bearer`：`auth_config.token`
- `auth_type=basic`：`auth_config.username/password`
- `auth_type=apikey`：`auth_config.api_key` + `auth_config.api_key_header`
- 签名请求（可选）：`auth_config.signature_secret`，由适配层按 query canonical string 计算 `X-Signature`。

### 6.1 真实分页字段与 delta cursor

- SAP OData
  - 分页字段：`$top` + `$skip`
  - delta 字段：`@odata.deltaLink` / `$deltatoken`
- ServiceNow Table API
  - 分页字段：`sysparm_limit` + `sysparm_offset`
  - delta 字段：`sys_updated_on`（通过 `sysparm_query` 过滤）

## 5. 测试

新增测试：

- `tests/test_connectors_contract_and_replay.py`
  - 契约校验失败（422）
  - 幂等重复提交（第二次 returned replayed）
  - 单系统 replay 汇总
  - 多系统 replay 汇总
