# 全球多地域部署与容灾方案（集团级）

## 1. 部署拓扑

- 总部双中心（控制面多活）
- 国内区域云（华北/华东/华南/西部）
- 海外区域云（按洲划分）
- 工厂边缘节点（本地缓存 + 轻量推理 + 断网可运行）

## 2. 流量与路由

- 全局 GSLB + 区域 API Gateway
- 优先就近接入与就近推理
- 跨域访问必须通过策略检查

## 3. 数据驻留

数据按驻留域分区：

- CN 域
- EU 域
- APAC 域
- Americas 域

策略要求：

- Prompt、检索上下文、工具输出默认域内处理
- 跨域仅传递策略允许的脱敏元数据

## 4. 容灾分级

- T0 交互问答链路：RTO ≤ 15min，RPO ≤ 5min
- T1 业务辅助链路：RTO ≤ 60min，RPO ≤ 30min
- T2 分析与离线链路：RTO ≤ 4h，RPO ≤ 2h

## 5. 演练机制

- 月度故障注入演练
- 季度跨区域切换演练
- 半年度全链路灾备演练

每次演练必须产出：

- 演练报告
- 风险清单
- 修复计划与责任人

## 6. 回退与熔断

- 模型级回退
- Skill 版本回退
- 工具级熔断
- 知识源级隔离

回退动作要求秒级生效，且全量审计。

## 7. 部署环境变量基线（Phase-3-3）

### 7.1 生产环境必配（控制面）

| 变量 | 建议值（生产） | 备注 |
|---|---|---|
| `EKB_DB_DRIVER` | `tidb` | 生产禁用 sqlite 主路径 |
| `EKB_TIDB_HOST` | `tidb-cluster-tidb` | 集群内服务名或VIP |
| `EKB_TIDB_PORT` | `4000` | TiDB SQL端口 |
| `EKB_TIDB_USER` | `ekb_app` | 最小权限账号 |
| `EKB_TIDB_PASSWORD` | Secret 注入 | 禁止明文写入 values |
| `EKB_TIDB_DATABASE` | `ekb_control_plane` | 控制面库 |
| `EKB_EVENT_PUBLISHER_BACKEND` | `pulsar` | 生产采用事件总线 |
| `EKB_PULSAR_SERVICE_URL` | `pulsar://pulsar-broker:6650` 或 TLS 地址 | 多可用区建议 TLS |
| `EKB_PULSAR_TOKEN` | Secret 注入 | 鉴权token |
| `EKB_PULSAR_TLS_ENABLED` | `true` | 跨域/公网建议开启 |
| `EKB_PULSAR_CA_CERT_PATH` | `/etc/ssl/certs/pulsar-ca.crt` | 与挂载证书一致 |
| `EKB_REDIS_URL` | `redis://redis-cluster:6379/0` | 语义/会话缓存 |
| `EKB_REDIS_MAX_CONNECTIONS` | `500` | 按连接池压测调优 |
| `EKB_REDIS_SOCKET_TIMEOUT_SECONDS` | `0.2` | 控制长尾延迟 |
| `EKB_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS` | `0.2` | 快速失败 |
| `EKB_NEO4J_URI` | `bolt://neo4j:7687` | 图谱推理存储 |
| `EKB_NEO4J_USERNAME` | `ekb_reader_writer` | 最小权限账号 |
| `EKB_NEO4J_PASSWORD` | Secret 注入 | 禁止明文 |
| `EKB_NEO4J_MAX_CONNECTION_POOL_SIZE` | `200` | 图查询并发调优 |
| `EKB_MILVUS_URI` | `http://milvus:19530` | 向量检索 |
| `EKB_MILVUS_TOKEN` | Secret 注入 | 禁止明文 |
| `EKB_MILVUS_DB_NAME` | `ekb_prod` | 生产向量库 |
| `EKB_AUTH_TOKEN` | Secret 注入 | MCP/A2A 认证 Token |
| `EKB_MCP_RATE_LIMIT_PER_MINUTE` | `6000` | MCP 调用速率限制 |
| `EKB_A2A_RATE_LIMIT_PER_MINUTE` | `12000` | A2A 发布速率限制 |
| `EKB_A2A_ENABLED` | `false` | A2A 消费者开关 |
| `EKB_A2A_TOPIC` | `persistent://group/a2a/default` | A2A 消费 Topic |
| `EKB_A2A_SUBSCRIPTION` | `yadea-ekb-a2a` | A2A 订阅名 |

## 10. 工业级扩展建议（10B/10M）

1. 控制面/数据面彻底拆分，控制面只处理治理与配置
2. Pulsar 按 tenant/region/agent 分区 topic + 代理层扩展
3. Redis/Neo4j/Milvus 分区部署与访问隔离
4. 审计写入异步化 + 冷热归档

## 11. CI 集成验证说明

已在 `.github/workflows/ci-multilang.yml` 中增加：

- Java job 的 Neo4j service
- Go job 的 Pulsar/Milvus services
- release-gate 作业，强制检查契约与双语手册存在

### 7.2 平台变量（可观测/元信息）

| 变量 | 建议值 | 用途 |
|---|---|---|
| `ENV` | `production` | 运行环境标识 |
| `DEFAULT_REGION` | `cn-north-1` | 默认区域路由 |
| `ENABLE_AUDIT` | `true` | 审计日志开关 |

## 8. Helm / K8s 配置对齐建议

当前 `infra/helm/ekb-control-plane` 已映射 TiDB/Pulsar 关键变量，但建议继续升级：

1. 在 Kustomize overlay 中区分 staging / production 的连接池与超时参数

已完成：

- Helm 已新增 `templates/secret.yaml`，敏感变量通过 Secret 注入
- Helm deployment 模板已改为 `secretKeyRef` 读取密码/Token
- Redis/Neo4j/Milvus 变量已加入 Helm values 与 deployment 模板

## 9. 架构落地现状（部署视角）

- 已落地：K8s 基线、Helm、Kustomize、HPA、PDB、NetworkPolicy
- 部分落地：生产 Secret 管理策略、全中间件变量在 Helm/K8s 模板的显式映射
- 待增强：跨区域演练报告模板、自动化DR切换脚本示例
