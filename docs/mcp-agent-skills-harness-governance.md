# MCP / Agent Skills / Harness 治理规范（企业生产版）

## 1. 设计目标

构建可审计、可回滚、可扩展的智能体治理体系，保证：

- 技能调用不越权
- 工具执行可追踪
- 版本变更可回归
- 数据驻留可证明

## 2. MCP Gateway 责任边界

MCP Gateway 是唯一工具调用入口，必须承担：

1. 身份认证（人、服务、Agent）
2. 策略授权（RBAC + ABAC）
3. 请求校验（JSON Schema）
4. 数据保护（脱敏、密级过滤）
5. 执行管控（限流、超时、重试、熔断）
6. 审计追踪（请求、结果、上下文引用、策略决策）

## 3. Agent Skills 生命周期

## 3.1 元数据模型

每个 Skill 至少包含：

- skill_name
- version
- owner
- risk_level
- allowed_tools
- allowed_domains
- residency_scope
- input_schema
- output_schema
- changelog

## 3.2 状态机

- draft
- review
- staging
- production
- deprecated

状态推进必须满足对应门禁。

## 3.3 上线门禁

- 静态扫描通过
- 契约测试通过
- Harness 三套评测通过
- 安全审批通过（高风险技能）

## 4. Harness 评测体系

## 4.1 评测维度

- 质量：相关性、忠实性、可解释性
- 安全：注入防护、越权阻断、隐私保护
- 回归：结果稳定性、时延回归、成本回归

## 4.2 评测输入

- 标准问答集
- 真实回放样本（脱敏）
- 红队对抗样本
- 工厂场景专项样本

## 4.3 发布判定

所有关键指标达到阈值才允许晋级；不通过则自动阻断发布并生成差异报告。

## 5. 审计与合规

必须记录并长期保存以下审计字段：

- tenant_id
- region_id
- plant_id
- user_or_agent_id
- model_id
- skill_name
- tool_name
- policy_decision
- latency_ms
- token_usage
- citation_set

审计数据要求：

- 支持追责与回放
- 支持分域保存（数据驻留）
- 支持按监管要求导出

## 6. 风险控制清单

P0 风险：

- 跨租户数据泄露
- 未授权工具调用
- 跨境违规访问
- 版本升级导致质量崩塌

P0 对策：

- 强制域隔离 + 策略证明
- MCP Gateway 全量拦截
- Residency Policy 运行时校验
- Harness 作为强门禁
