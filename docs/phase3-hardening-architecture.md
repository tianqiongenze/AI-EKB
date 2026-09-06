# 三期生产硬化架构（TiDB + Java/Python/Go）

## 1. 文档约束回归

基于两份原始架构文档，三期必须满足：

- 关系库主选型：TiDB（非 PostgreSQL）
- 多语言分工：
  - Java SpringBoot + Spring AI Alibaba（知识图谱与企业知识推理）
  - Python FastAPI/Celery/LangGraph（检索、文档处理、Agent编排）
  - Go Gin/Casbin（对话、高性能鉴权与审计服务）
- 中心云 + 区域云 + 边缘节点
- Pulsar 多租户事件总线
- MCP + Agent Skills + Harness 治理闭环

## 2. 服务边界

## 2.1 Python 控制面

- MCP Gateway
- Skill Registry
- Harness Gate
- Outbox + Relay
- 审计查询与容量估算

## 2.2 Java Spring AI Alibaba 服务

- KGraph Service
- 图谱查询与关系推理
- 企业知识问答增强（与Python检索链路联动）

## 2.3 Go 高性能服务

- Dialogue/AuthZ/Audit 高并发接口
- Casbin 策略校验
- 低时延网关级扩展组件

## 3. 数据与事件

- TiDB：用户、权限、配置、审计与控制面数据
- Milvus：向量检索
- Neo4j：图谱
- Pulsar：知识事件总线（tenant/namespace/topic）

## 4. 部署策略

- 开发：SQLite本地回退 + 单机服务
- 预发/生产：TiDB 驱动强制启用
- K8s 多环境：Helm + Kustomize

## 5. 三语言职责矩阵（Phase-3-3）

| 语言/模块 | 核心职责 | 关键中间件访问模式 | 性能目标 |
| --- | --- | --- | --- |
| Java (Spring AI Alibaba / KGraph) | 知识图谱推理、企业知识关联推断、降级熔断控制 | Neo4j 批量关系查询/推理，Sentinel 资源保护 + fallback | 图谱推理P99 < 800ms，异常时稳定降级 |
| Python (Control Plane / Orchestrator) | MCP治理、Skill生命周期、Harness、事件中继、检索编排 | Pulsar 批量发布、Redis 批量缓存访问、Milvus/Neo4j 客户端池化 | 控制面API P99 < 300ms，Relay批量稳定吞吐 |
| Go (Gateway / AuthZ / Dialogue Route) | 低时延入口路由、鉴权、审计事件快路径 | Cache/Event/Graph/Vector 适配器接口（批量读写优先） | 网关路由P99 < 120ms，鉴权P99 < 80ms |

## 8. 分层最终形态（强制执行）

### 8.1 Go Edge Gateway（数据平面）

职责：

- TLS 终止
- 鉴权
- 限流（global/authz/route + tenant-route）
- 路由与流量整形（canary 分流）
- 超时预算
- 重试预算
- 熔断
- 快速失败与背压

原则：

- 只做薄腰层
- 禁止重业务逻辑与复杂推理进入网关热路径

### 8.2 Java Capability Gateway/Service（控制/业务平面）

职责：

- 复杂策略评估
- 图谱/规则推理
- 复杂聚合
- 企业治理决策

原则：

- 重逻辑全部下沉
- 网关只调用能力层结果，不承载复杂决策流程

能力层标准接口（当前实现）：

- `/kgraph/policy/evaluate`
- `/kgraph/aggregate/insights`
- `/kgraph/governance/decision`

## 6. 中间件高性能访问策略矩阵

| 中间件 | 访问策略 | 实现要点 | 回退策略 |
| --- | --- | --- | --- |
| Redis | 批量读取 + pipeline 批量写入 | mget/mset+ttl；连接池上限可配；短超时 | 读超时降级到无缓存路径 |
| Pulsar | Producer batching + 压缩 + 有界队列 | 批量消息、低发布延迟窗口、block_if_queue_full | 关键路径回退至内存发布器并记录审计 |
| Neo4j | 批量 UNWIND 写入与合并 | 单次批处理关系写；连接池参数化 | 图谱失败时返回规则化fallback推理结果 |
| Milvus | 批量 upsert + TopK 搜索参数优化 | 向量搜索参数固定模板（COSINE + ef） | 向量检索失败回退关键词/规则检索 |
| A2A | Envelope + 幂等键 + DLQ | 消息去重、优先级通道、重试策略 | 失败进入DLQ并触发人工/自动补偿 |

## 7. 延迟预算与SLO建议

| 链路 | 预算 (P99) | 说明 |
| --- | --- | --- |
| API Gateway (Go) | 120ms | 包含鉴权和路由决策，不包含重推理 |
| Control Plane (Python) | 300ms | 包含策略校验、审计落库、事件入队 |
| KGraph Reasoning (Java) | 800ms | 含图谱推断与降级判断 |
| 端到端首包（缓存命中） | 500ms | 走缓存与轻路由路径 |
| 端到端首包（需推理） | 2s | 满足架构文档首Token目标 |
| A2A Publish | 80ms | A2A Envelope 入队与快速返回 |

> 说明：以上为工程基线预算，具体阈值需按生产压测与业务峰值分层（总部/区域/工厂）校准。
