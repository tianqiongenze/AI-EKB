# EKB 架构评审与重构方向报告（2026-09）

> 评审角色视角：高校 AI / 大数据专业教授级高工，兼具多个上亿级用户（10 亿+）、峰值百万并发互联网大厂项目的架构实战经历。
> 评审方法：全量代码走读（`src/enterprise_ekb` 5887 行 + Java/Go 服务 + infra/contracts）× 57→62 项测试实测 × 四道工程门禁运行 × 业界最佳实践联网对标。
> 证据规则：所有结论均给出 `file:line` 级证据，不做无凭据判断。

---

## 1. 评审结论（先行）

**综合评分：6.1 / 10（重构后现状；本次重构前约 5.8）。**

一句话判断：**这是一个"治理面设计优秀、控制面工程基线扎实、但距离百万并发生产目标仍有系统性差距"的可运行基线**。其契约优先、门禁文化、Outbox 可靠事件、多语言服务分工在同阶段项目中属于上游水平；但并发模型（全同步 handler）、分布式限流缺位、认证体系薄弱、可观测性不全四大项，若直接对外宣称支撑"100 万并发"，在生产流量下会在数千 QPS 量级率先暴露瓶颈。

| 维度 | 权重 | 得分 | 一句话评语 |
|---|---|---|---|
| 架构设计与领域建模 | 15% | **8.0** | 控制面/治理面/数据面分离清晰，契约优先，模式运用得当 |
| 可扩展性与并发就绪 | 15% | **4.5** | 全同步 handler + 进程内限流 + 无连接池，横向扩展被锁死 |
| 可靠性与数据一致性 | 12% | **6.5** | Outbox 生命周期完整，但 claim 非原子、多实例存在竞态 |
| 安全与合规 | 12% | **5.5** | 注入/SSRF 防护到位；认证体系与依赖组件凭据是短板 |
| 可观测性 | 8% | **5.5** | 本次补齐 /metrics 与降级日志后及格；仍缺 trace 与统一日志 |
| 工程质量与可维护性 | 10% | **5.5** | 1160 行 `create_app`、双 Store 重复实现，重构欠账明显 |
| 测试与质量门禁 | 10% | **6.0** | 门禁文化好；但元测试占比高、真实中间件集成测试缺失 |
| 部署与交付 | 8% | **7.5** | K8s/Helm/Kustomize/一键脚本齐全；本次修复 probe 指向错误 |
| 文档体系完备度 | 5% | **7.5** | 覆盖面与导航优秀；存在与代码的轻微漂移（本次对齐） |
| 规模目标符合度（100万并发） | 5% | **4.0** | 与目标量级存在代差，需要 P0 专项补课 |

加权合计：**6.1 / 10**。

---

## 2. 分项评析与证据

### 2.1 架构设计与领域建模 —— 8.0

亮点（值得肯定并保持）：

- **三面分离**：控制面（Python FastAPI）、治理面（Policy/Skill/Harness 门禁）、数据面（TiDB/Pulsar/Redis/Neo4j/Milvus）职责清楚；`create_app` 以工厂模式组装依赖（`src/enterprise_ekb/app.py:181`）。
- **契约优先**：`contracts/openapi + proto + pulsar-topics + a2a-protocol` 四类契约，且有 AST 级一致性门禁强制对齐（`scripts/check_contract_consistency.py:33`，35 路由/17 事件/14 A2A 字段实测通过）。
- **模式运用**：Outbox 状态机（claim/退避/dead，`storage.py:521-639`）、模板方法连接器（`connectors.py:262-276`）、Adapter 中间件客户端（`middleware_clients.py`）、Skill 状态机（draft→review→staging→production，含高危变更 changelog 强制校验）。
- **Go 网关是全仓最成熟的韧性实现**：令牌桶、熔断、error budget 降级、canary、背压（`services/go-gateway/main.go:639-1007`），可作为 Python 控制面韧性改造的参照系。

### 2.2 可扩展性与并发就绪 —— 4.5（最关键短板）

- **全同步 handler**：`app.py` 中 48 个处理函数全部为同步 `def`，`async def` 为 0。FastAPI 对同步 handler 走线程池（默认 40 线程/worker），单 worker 并发天花板被锁死；这与 README 宣称的"100 万+并发"存在两个数量级以上的差距。
- **进程内限流**：`rate_limiter.py:15-63` 为 threading.Lock 保护的进程内令牌桶。多副本部署时全局配额 = 单副本配额 × 副本数，既不能防超卖也不能防刷；限流必须上移到 Redis（滑动窗口/令牌桶 Lua）或网关层。
- **TiDB 无连接池**：`tidb_store.py:53-58` 为每线程一连接 + `ping(reconnect=True)`，无池化；百级线程并发下连接数与握手开销都会失控。
- **Outbox claim 竞态**：`storage.py:522-569` 的 SELECT→UPDATE 依赖进程内 `_outbox_lock`，多实例部署时同一事件可能被重复认领（有 instance id 缓解但非原子）。
- 缓解因素：Pulsar 批量发布、Neo4j UNWIND 批量、Redis pipeline/mget（`middleware_clients.py:101-148`）说明团队具备批处理意识，方向正确、深度不足。

### 2.3 可靠性与数据一致性 —— 6.5

- Outbox 完整生命周期（pending→processing→published/dead + 指数退避 + 超时回收）是同类项目少见的完整实现（`storage.py:521-639`）。
- 但如上所述，claim 非原子；Pulsar 降级到 InMemoryPublisher 曾无任何日志（本次已补 `app.py` warning），生产环境"事件悄悄丢到内存"是重大一致性风险，建议生产模式下 readyz 直接 fail（当前仅 `EKB_ENV=production` 时 readyz 检查 mismatch，已具备该机制）。

### 2.4 安全与合规 —— 5.5

- 到位项：SQL 全参数化（无 f-string 拼接）、表名正则+前缀白名单（`app.py:235-240`）、连接器 SSRF 防护（DNS 解析 + CIDR 校验，`app.py:317-348`）、审计双写、Helm Secret 化（`secret.yaml` 5 项凭据 secretKeyRef）。
- 短板项：
  - 认证为静态 Bearer Token，且**此前为非常量时比较 + 8 处内联重复**（本次已收敛为 `secrets.compare_digest` 单点 helper）。对照 MCP 官方安全基线（OAuth 2.1 + PKCE、token audience 校验、零未认证连接），差距是代际的（对标来源见 §3）。
  - `infra/k8s/deps/neo4j.yaml:21-24` 明文弱凭据（`neo4j/neo4j-password-1`），deps 中 Pulsar/Redis/Milvus 无认证——演示可用，生产不可接受。
  - token 缺省且非 production 时静默放行（本次已加显式 warning 日志）。

### 2.5 可观测性 —— 5.5（重构前 4.0）

- 本次补齐前：Python 侧零 metrics 端点、app/storage 零日志、异常静默降级三处（pulsar/milvus/neo4j）。
- 本次补齐后：`/metrics`（Prometheus 文本格式，含 HTTP 时延 summary + outbox 状态 gauge，`src/enterprise_ekb/metrics.py` + `app.py` 中间件）、三处降级 warning 日志。
- 仍缺：结构化 JSON 日志规范、分布式追踪（OpenTelemetry）、指标聚合栈（Prometheus/Grafana ServiceMonitor）。Go 侧已有 JSON 版 metrics（`main.go:1025-1046`）但非 Prometheus 格式。

### 2.6 工程质量与可维护性 —— 5.5

- `create_app` 1160 行（`app.py:181-1270`），35 个路由、全部业务逻辑与校验函数内嵌闭包——是最大的重构欠账。
- `tidb_store.py:255-403` 与 `storage.py:1118-1264` SQL 近逐行重复（继承复用方式导致两份 SQL 并存）。
- `_dump_alert` 双定义（本次已合并）、token bucket Python/Go 双实现（可接受，语言边界）。
- connectors.py:105-109 硬编码假数据（`occurred_at="2026-03-30"`）应改为数据驱动。

### 2.7 测试与质量门禁 —— 6.0

- 62 项测试全绿 + 四道门禁（契约一致性/Flink preflight/replay SLO/gateway SLO）可跑。门禁文化是本项目工程化的最大亮点之一。
- 短板：约 22 个测试文件为"元测试"（断言 YAML/脚本文本），防回归能力强但防逻辑错误能力弱；无真实 TiDB/Neo4j/Milvus/Pulsar 集成测试（testcontainers 级别）；无并发竞态测试。
- 两道 SLO 门禁曾因"阈值数组必须以 p95 开头"的脆弱正则误报失败（本次已修复为任意顺序/额外分位数容忍解析）——这本身说明门禁脚本也需要被测试。

### 2.8 部署与交付 —— 7.5

- HPA/PDB/NetworkPolicy（default-deny + 网关白名单）/资源 requests+limits 齐全；镜像钉 tag 0.2.0；一键构建/部署/关停脚本跨 macOS/Linux/Windows。
- 本次修复：base 清单 readinessProbe 误指 `/healthz`（与 Helm 模板不一致，`infra/k8s/base/deployment-ekb-control-plane.yaml:27`）——就绪探针曾经只会检查"进程活着"而非"依赖就绪"。

### 2.9 文档体系 —— 7.5

- 主导航（Mermaid mindmap）、架构/存储/运营/API/产品六线文档齐全且有三语 API 手册；本次已按当前实现重新对齐（见 §5 与 README/导航变更）。

### 2.10 规模目标符合度 —— 4.0

以 10 亿注册/1 亿 DAU/峰值 100 万并发连接的经验尺度衡量：当前单实例同步线程池模型 + 进程内状态（限流、Outbox 锁、内存 publisher）决定了**有效并发上限约在千级请求、万级连接**。达标路径不是"再加副本"，而是先完成 §4 P0 的并发模型改造。

---

## 3. 业界最佳实践对标（联网调研）

1. **检索架构**：2025 年企业级 RAG 的默认形态是**混合检索**（dense vector + BM25 sparse + graph traversal 融合，混合检索较纯向量可提升 NDCG 26-31%）；本项目已有向量/图/全文三索引布局，缺融合检索层与事件驱动的索引同步流水线。
   来源：[Atlan: Hybrid RAG](https://atlan.com/know/hybrid-rag/)、[Memgraph: HybridRAG](https://memgraph.com/blog/why-hybridrag)、[arXiv 2507.03608 基准](https://arxiv.org/html/2507.03608v1)、[Confluent: 事件流驱动知识同步](https://www.confluent.io/blog/enterprise-knowledge-management-with-rag-for-digital-native-companies/)
2. **MCP 安全**：MCP 官方安全最佳实践与 CSA 成熟度基线要求 **OAuth 2.1 + PKCE、token audience/claims 校验、短时效令牌、零未认证连接、网关集中鉴权**（GitHub #804 网关授权规范讨论中）。
   来源：[MCP Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices)、[CSA Agentic MCP Security](https://labs.cloudsecurityalliance.org/agentic/agentic-mcp-security-best-practices-v1/)、[Red Hat: MCP 认证授权](https://www.redhat.com/en/blog/mcp-security-implementing-robust-authentication-and-authorization)
3. **Outbox 演进**：轮询式 Outbox 在多实例下的标准解法是 **log-based CDC relay（Debezium Outbox Event Router）或 `FOR UPDATE SKIP LOCKED`** 原子认领；本项目文档已预判 CDC 方向（README §9.1），本报告将其正式列入 P1。
   来源：[Debezium Outbox 官方模式](https://debezium.io/blog/2019/02/19/reliable-microservices-data-exchange-with-the-outbox-pattern/)、[Decodable: Revisiting the Outbox Pattern](https://www.decodable.co/blog/revisiting-the-outbox-pattern)、[StackExchange: CDC 是 outbox 最具扩展性的排空方式](https://softwareengineering.stackexchange.com/questions/440390/how-to-scale-transactional-outbox-pattern-with-document-database)
4. **FastAPI 生产实践**：异步驱动（asyncmy/asyncpg）+ yield 依赖注入会话 + **连接池按 worker×池宽核算** + Alembic 迁移是当前共识；同步 handler 仅适合低并发管理接口。
   来源：[Towards AI: Production-Ready FastAPI](https://pub.towardsai.net/building-production-ready-apis-with-fastapi-sqlalchemy-and-alembic-a-complete-guide-a4656b7e700c)、[OneUptime: FastAPI+SQLAlchemy](https://oneuptime.com/blog/post/2026-01-25-fastapi-sqlalchemy-rest-apis/view)
5. **超大并发通用原则**（10 亿用户/百万并发经验校准）：无状态水平扩展、连接池前置（网关复用）、读写分离与多级缓存、背压与舱壁隔离、全局分布式限流、单元化部署——本项目 Go 网关已具备其中五项（值得肯定），Python 控制面目前一项都未落实。

---

## 4. 重构方向方案（P0/P1/P2）

### P0 —— 并发与安全补课（0-3 个月，达标底线）

| # | 事项 | 方案要点 | 验收口径 |
|---|---|---|---|
| P0-1 | **异步化热路径** | `/mcp/invoke`、`/vector/*`、`/graph/*`、`/a2a/*` 改 async；TiDB 走 asyncmy/SQLAlchemy async + 池化（池宽 = worker×pool_size 预算），Redis 走 `redis.asyncio` | 压测单 pod P99 < 50ms @ 2k QPS |
| P0-2 | **分布式限流** | Redis Lua 滑动窗口/令牌桶替换进程内 bucket（保留本地桶做两级限流：本地粗筛+全局精控） | 双实例压测全局配额精确 |
| P0-3 | **Outbox 原子认领** | `UPDATE ... SET status='processing', claimed_by=? WHERE id IN (SELECT ... status='pending' LIMIT n) AND status='pending'`（TiDB 支持该原子模式），废除进程内锁依赖 | 双实例并发 relay 零重复投递 |
| P0-4 | **认证升级 OAuth2.1/JWT** | 网关侧 JWT 校验（含 audience/exp），MCP/A2A 静态 token 仅保留内网兼容期；对齐 MCP 官方基线 | 无效/过期/错 audience 全部 401 |
| P0-5 | **deps 凭据整改** | k8s deps 全组件启用认证，凭据全部走 Secret/外部 KMS，删除明文 values | 安全扫描零明文凭据 |
| P0-6 | **可观测三件套** | 结构化 JSON 日志（统一 request_id 贯穿）、OpenTelemetry trace、Prometheus ServiceMonitor + Grafana 看板 + SLO 告警 | 一个 request_id 可串联三层日志 |

### P1 —— 结构重构与数据飞轮（3-6 个月）

1. **`create_app` 拆分**：按限界上下文拆 APIRouter（skills/mcp/a2a/connectors/datalake/domain/subagent），公共依赖（auth/audit/metrics/rate-limit）下沉为 FastAPI dependencies——预计 app.py 从 1270 行降至 ~300 行骨架 + 每域模块。
2. **双 Store 合并**：`SQLiteControlPlaneStore` 与 `TiDBControlPlaneStore` 改为组合（方言层只放差异 SQL），消除 150+ 行重复 SQL。
3. **CDC Outbox**：引入 Debezium（TiDB 兼容 MySQL binlog）Outbox Event Router → Pulsar，替换轮询 relay，事件时延从秒级降到百毫秒级。
4. **混合检索层**：vector + BM25 + graph 三路召回 → RRF 融合 → 重排；索引同步走事件流水线（对齐 §3.1 最佳实践）。
5. **Java 服务去 mock**：`KGraphReasoningService` 失败时返回 mock 知识的逻辑改为显式降级标记 + 熔断上报；治理规则从硬编码迁移到策略接口。
6. **测试体系升级**：testcontainers 集成测试（TiDB/Neo4j/Milvus/Pulsar）、Outbox 双实例竞态测试、门禁脚本自身的单测。

### P2 —— 规模化与生态（6-12 个月）

1. **单元化多活**：按 region/plant 分片的数据分级（Global/Regional/Local）落地为单元化部署，冲突消解与跨单元补偿流程。
2. **混沌工程例行化**：依赖故障注入演练（Pulsar 不可用/Redis 抖动/TiDB 主从切换），验证降级路径（复用 Go 网关 error budget 模型）。
3. **SLO 驱动成本优化**：以首 Token/P99/降级率为约束反推容量与缓存策略。
4. **MCP Registry 联邦与 A2A 生态扩展**：跨集群 Skill 注册发现、能力市场。

---

## 5. 本次已实施重构记录（2026-09，62 测试全绿 + 四门禁通过）

| # | 重构项 | 内容 | 涉及 |
|---|---|---|---|
| R1 | 就绪探针修复 | base 清单 readinessProbe `/healthz`→`/readyz`，与 Helm 模板对齐 | `infra/k8s/base/deployment-ekb-control-plane.yaml` |
| R2 | 认证收敛与加固 | Bearer 比较统一为 `secrets.compare_digest`（防时序侧信道）；8 处内联校验收敛为 `_bearer_matches` 单点；token 缺省非生产放行时输出显式 warning；三种鉴权语义（admin fail-closed/connector 带审计/业务可选）保持不变 | `app.py:146-175,231-241` |
| R3 | 重复代码消除 | `_dump_alert` 双定义合并为模块级单实现 | `app.py:91-101` |
| R4 | 可观测性基线 | 新增自研零依赖 Prometheus 文本格式 `/metrics`（HTTP 时延 summary + outbox 状态 gauge + 全局请求中间件，路由模板级标签防基数爆炸）；OpenAPI 契约同步登记 | `src/enterprise_ekb/metrics.py`、`app.py:212-253`、`contracts/openapi/control-plane.openapi.yaml` |
| R5 | 静默降级显性化 | Pulsar/Milvus/Neo4j 三处初始化失败补 warning 日志（含 exc_info） | `app.py:135-145,190-205` |
| R6 | 脆弱门禁加固 | 两道 SLO 门禁的阈值解析改为"数组内定位 p95/p99"，容忍 p90 与任意顺序 | `scripts/check_replay_e2e_slo.py:20-29`、`scripts/check_gateway_slo.py` |
| R7 | 测试补充 | 新增 5 项：metrics 端点格式、404 路径标签防基数、鉴权 401/200 语义、生产 fail-closed 保持 | `tests/test_metrics_and_auth_hardening.py` |

明确**不做**本次范围（需要专门压测环境或外部依赖）：异步化改造、Redis 分布式限流实现、OAuth2.1 接入——已列入 P0，避免无压测验证下的大规模并发模型切换。

---

## 6. 评审后的路线图一句话

先 P0 把"并发模型 + 认证 + 可观测"三块地基打牢（这是从 6.1 分到 7.5 分的路），再 P1 完成结构重构与混合检索飞轮（7.5→8.5），最后 P2 单元化多活与混沌工程（8.5→9+）。每一阶段以"门禁 + 压测报告 + 演练记录"作为晋升门槛，与本项目已有的 Harness 三门（质量/安全/回归）文化一脉相承。

---

# 二轮评审（2026-09，Litestar + Granian 迁移后）

> 二轮范围：项目群全量重打分、风控体系专项审查、DDD/事件驱动/读写分离/多级缓存专项、SDD/TDD/TOGAF/国标合规、GraphQL 引入评估。依据：迁移后 62/62 测试 + 四道门禁实测、Granian 真机冒烟、联网对标（前端跨端与风控漏斗模型）。

## 7. 框架迁移实录与效能影响

| 项 | 迁移前 | 迁移后 | 效能意义 |
|---|---|---|---|
| Web 框架 | FastAPI 0.1xx（Starlette 线程池模型） | **Litestar 2.24**（原生 msgspec 校验、更高吞吐） | 校验/序列化开销降低，官方基准约为 FastAPI 的 1.5-3 倍吞吐 |
| HTTP 服务器 | uvicorn（单事件循环） | **Granian 2.8**（Rust 核心，多 worker/多线程事件循环） | 同硬件连接承载与 TLS 握手能力显著提升 |
| handler 并发语义 | 隐式线程池（默认 40 线程/worker） | 显式 `sync_to_thread=True` ×36，事件循环零阻塞 | 明确并发模型，P0 异步化改造的就绪态 |
| 请求体校验 | Pydantic 直连 | Litestar Pydantic 插件（保留 Pydantic v2 模型） | 契约模型零改动，校验路径走 Litestar 管线 |
| 状态码契约 | POST→200 隐式 | POST→200 显式（`status_code=200` ×30） | 对外契约零漂移 |
| 校验错误语义 | 422 | 422（`ValidationException` 自定义 handler 保持） | OpenAPI 消费方零感知 |
| 回归结果 | 62 passed | **62 passed + 四门禁 PASS + Granian 真机冒烟 PASS** | 迁移以测试为安全网全程零回退 |

迁移中发现并固化的框架语义差异（沉淀为团队知识）：Litestar 以**保留参数名**识别连接对象（`request`）与请求体（`data`），路径参数必须类型化（`{p:str}`），应用级中间件对未匹配（404）请求不执行。

## 8. 项目群分项评分（v2）

| 子项目 | v2 得分 | v1 | 变化 | 评析 |
|---|---|---|---|---|
| Python 控制面（enterprise_ekb） | **6.5** | 6.1 | +0.4 | 框架就绪度提升；异步化/连接池/分布式限流仍待 P0 |
| Go 网关（go-gateway） | **7.5** | 7.5 | — | 熔断/背压/canary/error budget 齐备；缺 Prometheus 原生格式与认证 |
| Java KGraph（java-kgraph） | **5.0** | 5.0 | — | 真实 Neo4j + Sentinel 降级；治理硬编码与 mock 回退待除 |
| 部署资产（infra/） | **7.5** | 7.5 | — | HPA/PDB/NetPol/多集群包齐备；deps 凭据待整改 |
| 契约与门禁（contracts/ + scripts/） | **8.0** | 8.0 | — | 双风格 AST 门禁 + 四道闸，工程文化亮点 |
| **项目群综合** | **6.5** | 6.1 | **+0.4** | 从"可运行基线"到"高吞吐就绪基线" |

## 9. 风控体系专项审查（评分 4.5 / 10，最薄弱项）

### 9.1 现状清单（有 vs 缺）

| 防线 | 已具备 | 证据 | 缺失 |
|---|---|---|---|
| 限流 | 全局 + 租户/区域两级令牌桶 | `rate_limiter.py`、`app.py` 429 语义 | **分布式限流**（进程内桶，多副本配额失真）；无 IP/ASN 维度 |
| 防重 | 连接器幂等键唯一约束（replayed 计数）；sub-agent 幂等 | `README §4`、`storage.py` | MCP/A2A 调用无幂等键强制；无请求签名 |
| 防重放 | — | — | **无 nonce/时间戳/HMAC 签名**，静态 Bearer 可被重放 |
| 恶意注入 | SQL 全参数化、表名白名单、LIKE 通配符部分防护 | `app.py`、`storage.py:750` | LIKE 通配符转义不完备 |
| SSRF | DNS 解析 + CIDR 白名单 | `app.py` 连接器校验 | 无重定向后二次校验 |
| 边缘防护 | NetworkPolicy default-deny | `infra/k8s/base` | 无 WAF/边缘限速/Bot 管理 |
| 设备/人机 | — | — | 无设备指纹、无自适应验证码（对照漏斗模型全空缺） |
| 凭据治理 | Helm Secret 化、production fail-closed | `secret.yaml` | deps 组件弱凭据/无认证（neo4j 明文、Pulsar/Redis/Milvus 无认证） |
| 审计 | 全链路 audit 双写 + 失败审计 | `storage.py` | 审计查询无不可变/防篡改存储 |

### 9.2 大厂标准风控目标架构（漏斗式递进防御）

```mermaid
flowchart LR
    A[边缘层: WAF/IP信誉/JA3指纹] --> B[网关层: 分布式滑窗限流+配额]
    B --> C[身份层: OAuth2.1/JWT+设备指纹]
    C --> D[业务层: 幂等键+防重放签名+风险评分]
    D --> E[对抗层: 自适应验证码+行为基线]
    E --> F[审计层: 不可变审计+实时告警]
```

**P0 风控补课（对应调研：三层防线与漏斗模型）**：
1. Redis Lua 滑动窗口分布式限流（IP/租户/设备三键，本地桶做一级粗筛）
2. 请求签名：HMAC-SHA256 + timestamp ± 300s + nonce 去重（Redis SETNX TTL）——消灭重放窗口
3. MCP/A2A 调用强制幂等键 + 去重窗口
4. deps 组件全面启用认证，凭据入 Secret/KMS
5. 等保三级审计基线：审计留存 ≥ 6 个月 + 防篡改（append-only 存储/日志 WORM）

## 10. DDD / 事件驱动 / 读写分离 / 多级缓存专项

| 维度 | 得分 | 现状 | 提升方向 |
|---|---|---|---|
| DDD | 6.0 | 限界上下文雏形清晰（skills/mcp/a2a/connectors/datalake/domain/subagent 七个），但代码上全部内嵌 `create_app` 闭包，无分包；Skill 状态机/连接器模板方法是好的战术模式 | 按上下文拆 APIRouter + 领域服务包；领域事件命名已规范（`domain.capability.upserted` 等 17 类），保留 |
| 事件驱动 EDA | 7.0 | Outbox 完整状态机 + Pulsar 批量发布 + topic 契约；消费端 A2A intent 分派 | 消费端幂等表、DLA 管理界面、CDC relay（Debezium）替代轮询、schema registry |
| 读写分离 | 4.5 | TiDB 单端点读写混跑；audit 查询/coverage/容量估算均为读多写少 | TiDB读走 follower + `tidb_store` 只读 DSN；写主读从 + 缓存前置；热点审计查询降级 ES/Lindorm 类二级索引 |
| 多级缓存 | 5.0 | **L2 Redis wrapper 已建但控制面未实际接入（当前命中率≈0）**；Go 网关有 2min 进程内 go-cache | 见下表——命中率提升空间是本项目最大的"免费"性能来源 |

### 10.1 多级缓存设计与命中率提升空间测算

| 层级 | 内容 | TTL | 预期命中率 | 失效机制 |
|---|---|---|---|---|
| L1 进程内（LRU，≤10k 项） | Skill manifest、Policy 判定结果、域能力目录 | 30-60s | 90%+（读多写少） | 短 TTL + 事件主动失效 |
| L2 Redis | 向量检索结果（查询归一化 hash）、能力检索、审计游标 | 5-30min | 热点查询 30-60% | `domain.capability.upserted` 等事件驱动失效 |
| L3 源（TiDB/Milvus/Neo4j） | 全量数据 | — | — | — |

综合测算：检索类接口缓存后源库 QPS 可降 40-70%，P99 显著改善；**当前命中率 0% → 目标 ≥55% 是明确的、可度量的提升空间**。失效通道复用既有 Outbox 事件（发布后 fan-out 到 Redis del），是事件驱动架构对缓存层最直接的贡献。

## 11. SDD / TDD / TOGAF / 国标合规评估（5.5 / 10）

| 标准 | 符合度 | 证据与差距 |
|---|---|---|
| SDD（规格驱动开发） | 7.0 | OpenAPI/proto/pulsar-topics/a2a-protocol 四契约 + AST 门禁强制代码-契约一致，是教科书级 SDD 实践；差距：规格→测试用例的推导未自动化（可引入 contract-test 生成） |
| TDD | 5.0 | 62 测试 + 四门禁 + 元测试防回归；差距：测试以实现后补为主，无 red-green-refactor 流程证据；建议新模块强制 TDD（connectors/异步化改造先行） |
| TOGAF | 6.0 | 四域架构文档齐备（业务/数据/应用/技术），Harness 三门 = 架构治理雏形；差距：无 ADM 迭代记录、Architecture Repository 未分层（基线/目标/过渡态）、无 stakeholder 管理视图 |
| 国标 | 4.0 | **GB/T 8567**（文档编制）：文档齐全但未按 8567 模板组织；**GB/T 25000.51（SQuaRE）**：未按质量特性（功能性/性能效率/兼容性/易用性/可靠性/信息安全性/维护性/可移植性）建立度量基线；**GB/T 22239（等保 2.0 三级）**：访问控制/安全审计有雏形，但双因子认证、入侵防范、审计留存 6 个月、数据完整性保护存在系统性差距；**GB/T 8566**（生存周期）：阶段划分与仓库 phase 文档可映射，未显式声明。建议：以等保三级为安全底线目标，SQuaRE 八特性建立度量面板，8567 模板对齐核心交付文档 |

## 12. GraphQL 引入评估（结论：治理面不引入；P2 数据面可选只读 BFF）

| 评估项 | 分析 |
|---|---|
| 性能收益 | GraphQL 网关解析/校验本身增加 ~5-15% CPU 开销；聚合场景（前端一次拉取"能力+文档+图谱"复合视图）可把 3-5 次 round-trip 合并为 1 次，端到端时延收益真实但**小于异步化改造的收益**（当前瓶颈在同步 IO 与连接模型，不在接口往返次数） |
| 复杂度成本 | N+1 需要 DataLoader；治理面 36 端点的契约门禁体系需为 GraphQL 重建（schema 注册/变更破坏性检测）；客户端缓存范式改变 |
| 安全风险 | 查询深度/复杂度攻击面新增（需 depth limit + cost analysis + persisted queries）；与现有 Bearer 体系叠加需重新设计鉴权粒度 |
| 建议 | **治理面（skills/mcp/policy/audit）维持 REST+契约门禁**；**P2 阶段在检索聚合域引入只读 GraphQL BFF**（strawberry，persisted queries only，depth≤5），服务管理台与 IM 机器人的复合视图；预期该场景 round-trip 3-5→1、首屏 TLVC 改善 20-40%，但优先级排在 P0 异步化与分布式限流之后 |

## 13. 二轮结论

项目群综合 **6.5/10**（v1 6.1）。下一步杠杆排序：**P0-1 异步化热路径 > P0-2 分布式限流与请求签名（风控 4.5 分的直接补课）> 多级缓存启用（命中率 0→55%，性价比最高）> P0-6 可观测三件套 > P1 create_app 拆分（DDD 落地载体）**。前端多端方案见 `docs/frontend-multiclient-design.md`。

## 14. P0 落地实录（2026-09 第三轮，68/68 测试 + 四门禁通过）

| P0 项 | 状态 | 落地内容 | 验证 |
|---|---|---|---|
| P0-3 Outbox 原子认领 | ✅ 已落地 | SQLite store 与 TiDB store 对齐为单条原子 UPDATE（`id IN (SELECT…LIMIT)` + status 守卫），删除进程内 `_outbox_lock` 依赖，多实例 relay 不再可能重复认领 | `test_storage_and_outbox` 全绿 |
| P0-2a 分布式限流 | ✅ 已落地 | `risk_control.DistributedRateLimiter`：Redis Lua 原子滑窗（`EKB_RATE_LIMIT_BACKEND=redis` 启用），Redis 故障自动降级内存滑窗；MCP/A2A 五个热点端点接入"本地粗筛+全局精控"两级限流 | 专项测试（含降级路径） |
| P0-2b 防重放/防刷 | ✅ 已落地 | `AntiReplayMiddleware`（纯 ASGI）：HMAC-SHA256 签名（method+path+timestamp+nonce+body 摘要）±300s 时间窗 + Redis/memory 单次 nonce；`X-EKB-Timestamp/Nonce/Signature` 三头；默认关闭（`EKB_REQUEST_SIGNING_SECRET` 为空零开销） | 6 项专项测试（缺失头/过期/坏签名/重放/放行） |
| P0-4 JWT 认证 | ✅ 已落地 | `verify_bearer_credential`：静态 Token 常量时比较 + HS256 JWT（exp 必验、aud 可选校验），admin/connector/业务三条鉴权路径统一走该验证器；静态 Token 向后兼容 | 单测 + 端到端（admin 端点 JWT 200） |
| P0-5 deps 凭据整改 | ✅ 已落地 | neo4j 明文凭据 → secretKeyRef；redis `--requirepass` 注入；pulsar-standalone 启用 token 认证（secret 挂载密钥）；milvus 启用 authorizationEnabled + minio 双键 secret 化；新增 `credentials-secret.example.yaml` 模板 | 全 deps YAML 解析校验 |
| P0-6 可观测（代码侧） | ✅ 已落地 | `logging_setup`：`EKB_LOG_FORMAT=json` 结构化日志（ts/level/logger/message/request_id）；ASGI 中间件每请求生成 request_id 并回写 `X-Request-ID` 响应头；新增 ServiceMonitor 清单（`infra/k8s/observability/`） | 全量回归 |
| P0-1 异步化热路径 | ⏳ 部分就绪 | 框架层全异步（Litestar/Granian + ASGI 中间件 + `sync_to_thread` 零阻塞事件循环）；DB 驱动层 async 改造需 aiosqlite/asyncmy + 真实压测环境，列为下一专项 | — |

风控评分更新：**4.5 → 6.0**（重放攻击面关闭、分布式限流就绪、凭据明文清零；边缘 WAF/设备指纹/自适应验证码为 P1+ 外围设施）。项目群综合评分相应上调至 **6.7 / 10**。

## 15. 第三轮落地：多级缓存 + create_app 拆分（2026-09，72/72 测试 + 四门禁通过）

### 15.1 多级缓存启用（评审 §10.1 方案落地，命中率 0 → 可度量）

- 新增 `cache.MultiLevelCache`：L1 进程内 TTL+LRU（默认 60s/10k 项）+ L2 Redis JSON（`EKB_CACHE_BACKEND=redis`，默认 300s），L2 故障自动降级。
- 接入点：策略判定缓存（key 含 **registry epoch**，skill 注册/晋级即失效——晋级后允许判定零延迟生效，测试固化）、域能力 search/coverage（upsert/bootstrap 前缀失效，防陈旧读测试固化）、向量检索结果（upsert 前缀失效）。
- 命中率可观测：`ekb_cache_hits_total{layer}` / `ekb_cache_misses_total` / `ekb_cache_invalidations_total` 进 `/metrics`，评审设定的"0%→≥55%"目标自此有度量口径。

### 15.2 create_app 拆分（P1 结构欠账 #1 清偿，DDD 载体落地）

| 项 | 拆分前 | 拆分后 |
|---|---|---|
| app.py | 1434 行（36 路由 + 全部装配 + 闭包） | **75 行纯装配层** |
| 路由组织 | 单体闭包 | `api/` 包 10 个限界上下文模块：health / observability / skills / mcp / governance / a2a / subagent / dataops / domain / connectors |
| 共享依赖 | 闭包变量 | `api/context.py`：`ControlPlaneContext` + `build_context()`（基础设施/服务装配）+ 鉴权与校验方法 |
| 契约门禁 | 仅扫 app.py | 扩展扫描 `api/*.py`（路由 + Outbox 事件类型），36 路由 / 17 事件契约继续 1:1 强制 |

### 15.3 风控小修补（P0 遗留尾项）

- LIKE 通配符转义（`\` + ESCAPE 子句，SQLite/TiDB 双方言），用户输入无法加宽匹配。
- 连接器假时间戳（硬编码 `occurred_at="2026-03-30"`) → 真实时钟 UTC。
- 连接器 HTTP 客户端显式 `follow_redirects=False`（SSRF 纵深防御：重定向不得绕过 CIDR 校验）。

### 15.4 P0-1 异步化决策记录

判定：**框架层已全异步**（Litestar 事件循环零阻塞 + `sync_to_thread` 工作线程执行 + 纯 ASGI 中间件）；进一步收益在 **DB 驱动层 async 化（aiosqlite/asyncmy）**，但存储层同时被同步消费者使用（OutboxRelay、A2A 消费线程），直接改 async 会破坏其契约。路线：P1.5 先将 relay/消费者改造为异步任务化，随后存储层提供 async 门面（async 门面 + to_thread 过渡 → 原生 async 驱动），需配合真实 TiDB 压测环境验收。**不做无压测验收的假异步改造。**

综合评分更新：工程质量 5.5 → **7.0**（结构欠账清偿），可扩展性 4.5 → **5.0**（缓存层就绪）。项目群综合 **6.7 → 6.9 / 10**。

## 16. 第四轮落地：后续待办清偿（2026-09-07，79/79 测试 + Java 11/11 + 前端构建通过）

| 待办 | 状态 | 落地内容 |
|---|---|---|
| P1.5 OutboxRelay 后台任务化 | ✅ | Litestar lifespan 异步循环（`EKB_RELAY_BACKGROUND_ENABLED`，原子认领保证多副本安全），relay 运行/发布/失败指标进 /metrics；默认关闭（生产开启），测试验证"免手动 /events/relay 自动发布" |
| P1 混合检索融合层 | ✅ | `retrieval.py`：RRF 融合（k=60）+ 三腿架构（lexical=域能力目录 / vector=Milvus / graph=可插拔钩子），`POST /retrieval/hybrid`（契约已登记），不可用腿降级不失败（`degraded` + 分腿计数）；对齐 2025 混合检索（dense+sparse+graph）业界默认 |
| CDC Outbox | ✅ 资产就绪 | `infra/cdc/`：Debezium Server 配置（TiDB binlog → EventRouter → Pulsar）+ 部署/验收文档；轮询 relay 保留为降级路径 |
| Java 去 mock | ✅ | Neo4j 不可用/空结果时不再返回编造知识（设备/故障/点检），改为 `degraded:neo4j_unavailable / graph_empty_result` 显式降级标记；Java 11/11 测试通过 |
| 前端 M1 管理台 | ✅ 最小落地 | `web/admin/`：React18+Vite+TS，W3C DTCG 设计令牌单源，四页（运行健康/容量估算/Skill 三级晋级/审计查询），构建产物 gzip 47.6KB（<200KB 预算） |
| 测试环境隔离 | ✅ | `tests/conftest.py` autouse 环境快照还原——根治多测试裸改 `EKB_AUTH_TOKEN`/`EKB_ENV` 的顺序泄漏 |
| 双 Store 方言合并 | ⏸ 判定 | 需先有 testcontainers 真 TiDB 集成测试兜底；无验证环境下的方言合并风险 > 收益，列为 testcontainers 落地后首个重构 |
| testcontainers 集成测试 | ⏸ 判定 | Docker 工具链已就绪；需拉取 TiDB/Neo4j/Milvus 镜像与 CI 时长预算，列为下一专项首项 |

综合评分更新：测试与门禁 6.0 → **6.5**（隔离根治+混合检索/后台 relay 测试），可扩展性 5.0（relay 异步任务化），功能完备度提升。项目群综合 **6.9 → 7.0 / 10**。

---

# 三轮评审（2026-09-07，含四轮落地全证据）

> 评审输入：79/79 Python 测试 + Java 11/11 + 前端构建（gzip 48KB）实测、四道门禁、admin M1.5 组件测试、联网对标（RRF 生产默认实证：hybrid NDCG +26-31%、GraphRAG 多跳 86% vs 32%——来源 [Atlan](https://atlan.com/know/hybrid-rag/)、[MongoDB RRF](https://www.mongodb.com/resources/basics/reciprocal-rank-fusion)、[arXiv 2408.04948](https://arxiv.org/abs/2408.04948)）。

## 17.1 项目群重打分（三轮）

| 子项目 | v3 | v2 | 变化动因 |
|---|---|---|---|
| Python 控制面 | **7.0** | 6.5 | 混合检索层 + 后台 relay + 缓存指标化；app.py 75 行装配 |
| Java KGraph | **5.5** | 5.0 | 去 mock（degraded 标记），假知识回退清零；治理硬编码仍在 |
| 前端 web/admin（新增子项） | **6.5** | — | M1.5：组件化/暗色令牌/3 组件测试；缺 e2e、i18n、CI |
| Go 网关 | 7.5 | 7.5 | — |
| 部署资产（含 CDC） | **7.5** | 7.5 | +Debezium CDC 资产；deps 凭据已整改 |
| 契约与门禁 | **8.0** | 8.0 | 扩展至 api/ 包 + 新契约；37 路由对齐 |
| **综合** | **7.2** | 7.0 | +0.2 |

## 17.2 十维度更新（证据口径）

| 维度 | v1 | v3 | 关键证据 |
|---|---|---|---|
| 架构设计与领域建模 | 8.0 | **8.2** | 10 个限界上下文模块 + context 载体；api/ 包 2114 行结构化 |
| 可扩展性与并发就绪 | 4.5 | **5.5** | 后台 relay 异步任务化（原子认领多副本安全）；事件循环零阻塞 |
| 可靠性与一致性 | 6.5 | **7.2** | Outbox 生命周期 + 后台自动发布测试固化（免手动触发） |
| 安全与合规 | 5.5 | **6.0** | 签名防重放/JWT/凭据整改/LIKE 转义/SSRF 纵深；边缘设施仍缺 |
| 可观测性 | 4.0 | **6.0** | /metrics（HTTP+Outbox+缓存+relay 四族指标）+ request_id 贯穿 + JSON 日志；缺 trace |
| 工程质量 | 5.5 | **7.0** | 结构欠账清偿；双 Store 仍重复（有据缓办） |
| 测试与门禁 | 6.0 | **6.5** | 79 项 + conftest 环境隔离根治 + 组件测试；缺 testcontainers |
| 部署与交付 | 7.5 | **7.8** | CDC 资产；前端产物入仓 |
| 文档体系 | 7.5 | **8.0** | 评审 §1-§17 全链路可追溯 |
| 规模目标符合度 | 4.0 | **4.5** | 并发模型就绪度提升；仍需真实压测验收 |
| **加权综合** | **6.1** | **7.2** | 四轮：6.1→6.5→6.9→7.0→7.2 |

## 17.3 风控专项（三轮复核：6.0，达成项与开放项）

已闭环：重放攻击面（HMAC+时间窗+nonce）、分布式限流（Redis 滑窗）、凭据明文（全部 Secret 化）、注入（LIKE 转义补齐）、SSRF（显式禁重定向）、JWT 认证、生产 fail-closed、审计双写。
开放项（按风险排序）：① 边缘 WAF/Bot 管理（需云 WAF 或网关插件——Go 网关已有背压/熔断基础，可加 IP 信誉中间件）② 设备指纹+自适应验证码（需客户端 SDK，依赖前端 M2）③ 账号维度风控（登录态/权限模型尚未建立——当前是服务身份而非用户身份体系）④ 审计防篡改存储（WORM）。**结论：服务间调用风控已达标，用户侧风控体系尚未建立（依赖 M2 账号体系），评分止步 6.0 的原因即在于此。**

## 17.4 DDD / 事件驱动 / 读写分离 / 多级缓存：贡献与影响量化

| 机制 | 对各服务的贡献 | 度量 |
|---|---|---|
| DDD 拆分 | 控制面 10 上下文模块并行开发、契约门禁按模块扩展；Java/Go 服务边界不变 | api/ 13 文件 2114 行；门禁 37 路由对齐 |
| 事件驱动 | Outbox→Pulsar 17 类事件 = 缓存失效通道 + 数据飞轮输入 + CDC 兼容；后台 relay 让"写路径零阻塞发布"成为默认 | relay 自动发布测试；`ekb_outbox_relay_*` 指标 |
| 读写分离 | 未启用（4.5 分维持）——audit/coverage 类读查询仍走主库；缓存层先行对冲 | 待 TiDB 副本接入 |
| 多级缓存 | 策略判定/域能力/向量检索三路径命中即省一次源库往返；命中率指标实时可查 | `ekb_cache_hits_total{layer=l1|l2}` / `ekb_cache_misses_total` |
| **命中率提升空间** | **仍有，量化如下**：已覆盖 3 读路径；未覆盖的 audit query（读多写少，预估 80%+）、capacity estimate（纯函数，预估 95%+）、supervision scan 摘要（短 TTL，60%+）接入后综合命中率可再 +15-25 个百分点；再往上受写频繁路径限制，需 L2 Redis 全量接入（当前 L2 依赖 `EKB_CACHE_BACKEND=redis`，生产开启后生效）+ HTTP 层 ETag（/metrics 抓取去重） | 指标面板已就绪，生产流量进来即可实测 |

## 17.5 GraphQL 评估结论（三轮复核：仍未引入，且这是对的）

**现状：未引入**（治理面维持 REST + 契约门禁；无 GraphQL 依赖进入运行时）。性能提升实际来自：缓存三路径（源库往返削减）、后台 relay（发布路径去手动化）、混合检索（召回质量，对齐 NDCG +26-31% 的行业实证）。维持不引入的量化理由不变：GraphQL 解析/校验开销 5-15% CPU、治理面 37 端点契约门禁体系需重建、N+1 需 DataLoader——而当前瓶颈（同步 IO 驱动层）它解决不了。**P2 触发条件**：检索聚合域出现 ≥3 路 round-trip 的真实前端场景（M2 移动端/IM）时，以 strawberry 只读 BFF + persisted queries 引入。届时预期聚合场景 round-trip 3-5→1，但不改变综合 P99 曲线。

## 17.6 前端多端方案（M1.5 达成 + 大厂标准下一阶段）

已达成（M1.5）：设计令牌单源（亮/暗双主题）、组件化（Card/StatusDot/JsonView）、组件测试（vitest+RTL 3 项）、构建门禁（tsc strict + vite，gzip 48KB<200KB 预算）。
下一阶段（按大厂标准）：① **M2 移动端**（uni-app x，鸿蒙硬要求）与小程序同仓共码 ② 管理台微前端拆分（skill/审计/容量三子应用，Module Federation）③ E2E（Playwright）+ Lighthouse CI 进流水线 ④ i18n（zh-CN/en）与无障碍审计 ⑤ 大屏端（ECharts 车间看板）。

## 18. 四轮评审（2026-09-07 下午，83/83 测试 + 四门禁全绿）

### 18.1 本轮重构落地

| 项 | 内容 | 依据 |
|---|---|---|
| 缓存第三/四腿接入 | **audit query**（TTL 30s，追加型日志免失效）与 **capacity estimate**（TTL 3600s，纯函数按 payload 哈希）——注意 capacity 的事件副作用保留在缓存之外，每次调用仍发 `capacity.estimated` | 兑现 §17.4 "+15-25pp" 承诺的可执行部分；supervision scan **有意不缓存**（scan 有发事件副作用，缓存会吞掉监督事件） |
| 风控新发现修复 | `POST /capacity/estimate` 原本**完全未鉴权**（任意调用+写事件）→ 补 Bearer 校验（token 未配置时行为不变，向后兼容） | 风控专项复核新发现 |
| 检索层对标升级 | **加权 RRF**（`weights`，下压弱势召回源）+ **重排钩子**（`reranker`，供 cross-encoder 接入）——对标 2026 实证：RRF 为生产默认（hybrid NDCG +26-31%）、强势召回源应加权 | [Atlan](https://atlan.com/know/hybrid-rag/)、[MongoDB](https://www.mongodb.com/resources/basics/reciprocal-rank-fusion)、[arXiv 2408.04948](https://arxiv.org/abs/2408.04948) |
| testcontainers 判定 | **实测 Docker 守护进程未运行**（rancher-desktop socket 无响应、colima 未启动）；不擅自启动用户 VM → 维持缓办，启动后即为下一专项首项 | §16/§17 判定延续，本次补运行时证据 |

### 18.2 国标合规矩阵（GB/T 25000.51-2016 RUSP 八特性）

对标口径：GB/T 25000.51-2016（现行有效，2016 修订版将 信息安全 与 兼容性 纳入特性）；国际对应 ISO/IEC 25010:2023 已扩至 9 特性（新增 safety），未来国标修订跟进。

| 特性 | 符合度 | 证据与差距 |
|---|---|---|
| 功能完备性 | 7.5 | 37 端点契约 1:1、17 类事件、12 业务域覆盖（domain/capabilities/coverage 审计） |
| 功能正确性 | 7.0 | 83 Python + 11 Java + 3 前端测试全绿；四门禁；缺真机中间件集成测试 |
| 性能效率 | 5.5 | 缓存四腿 + 异步 relay + Granian；无公开压测报告（perf/tiered 有框架） |
| 兼容性 | 7.0 | SQLite/TiDB 双驱动、OpenAPI/Proto 双契约、MySQL 方言 ESCAPE 语法一致 |
| 信息安全性 | 6.5 | 防重放/JWT/限流/凭据 Secret 化/LIKE 转义/SSRF 纵深；缺 WORM 审计与等保三级双因子 |
| 可靠性 | 7.0 | Outbox 全生命周期 + 原子认领 + dead-letter + 后台自愈 |
| 维护性 | 7.5 | 10 上下文模块、75 行装配层、契约门禁防漂移、CHANGELOG 纪律 |
| 可移植性 | 7.5 | K8s/Helm/Kustomize/Compose/裸机五形态 + 双驱动 + 无 OS 绑定 |

### 18.3 评分更新

- 安全与合规 6.0 → **6.3**（capacity 鉴权缺口关闭、国标矩阵建立）
- 缓存：命中率仪表盘四腿齐备（policy/domain/vector + audit/capacity），生产流量进入即实测
- **综合 7.2 → 7.3**；演进曲线：6.1→6.5→6.7→6.9→7.0→7.2→7.3

### 18.4 明确不做与原因（本轮）

- **启动 Docker VM 跑 testcontainers**：守护进程未运行且启动用户 VM 属环境变更，不擅自执行；文档已给出启动后首项执行路径。
- **supervision scan 缓存**：副作用语义（发监督事件），缓存将静默吞事件——明确排除并记录。

## 19. 五轮落地：前端多端下一阶段并行执行（2026-09-07）

| 大厂标准排序项 | 状态 | 落地内容 |
|---|---|---|
| M2 移动端 | ✅ 骨架落地 | `web/mobile/`：uni-app Vue3 基座 14 文件（健康页+容量页、pages.json/manifest、鸿蒙配置骨架），**令牌同源**（tokens.json→tokens.scss 18/18 核对一致），API 客户端与管理台语义对齐；HBuilderX/CLI 构建路径与 uni-app x（UTS→ArkTS）迁移路线写入 README |
| i18n | ✅ | 极轻量自研（无 i18next 依赖）：类型安全 t()、localStorage 持久化、zh-CN/en 双包（漏译编译报错）、语言切换按钮；5 项 i18n 测试 |
| Playwright E2E + Lighthouse CI | ✅ 流水线就绪 | `e2e/`（playwright 配置 + 冒烟用例：控制台渲染/页签导航/主题切换 + 控制面 /healthz 检查）+ `.github/workflows/e2e-lighthouse.yml`（chromium 安装→E2E→Lighthouse 断言→**bundle gzip<200KB 硬门禁**）；浏览器安装后本地 `npx playwright test` 可跑 |
| 车间大屏 | ✅ | `pages/WorkshopScreen.tsx`：纯内联 SVG（甜甜圈 Outbox 分布 + relay 吞吐条形图），零新增依赖（保首包预算），设计令牌复用；已接入第 5 个导航页签（i18n key 同步） |
| 微前端拆分 | ⏸ 排序后移 | 管理台当前单团队迭代，拆分收益<成本；触发条件：≥2 团队并行改造管理台时启动（Module Federation） |
| 首包预算 | ✅ 保持 | 新增大屏页+i18n 后 gzip 49.9KB（预算 200KB，占用 25%） |

前端测试矩阵：**8/8 组件测试**（i18n 5 + App 3）；构建门禁 tsc strict + vite 维持。

本轮无 Python 代码变更（79/79 + 四门禁维持全绿）；评分：前端子项 6.5 → **7.0**（多端矩阵成形：admin M1.5 + mobile M2 骨架 + 大屏 + E2E/CI），综合维持 **7.3**。

## 20. 六轮落地：读写分离/消费幂等/ETag + TOGAF ADR 档案（2026-09-07，87/87 测试）

| 维度 | 本轮重构 | 验证 |
|---|---|---|
| 读写分离（4.5→5.5） | `ReplicaRoutingStore`：读方法路由副本（SQLite 同文件无滞后 / TiDB 副本最终一致），relay 保持主库；`EKB_READ_REPLICA_DB_PATH`/`EKB_TIDB_READ_HOST` 配置启用，未配置零行为变化 | 路由单测 + 同文件双库集成测试（写主读副） |
| 事件驱动（7.2→7.5） | A2A 消费端幂等：dispatcher 按 `message_id` 去重（600s 窗口），at-least-once 投递变为有效单次处理 | 重投递 no-op 测试（duplicates 计数） |
| 多级缓存 | HTTP 层 ETag：/readyz、/metrics 支持 If-None-Match→304；/metrics 豁免自观测（消除自引用棘轮） | 304 测试 ×2 端点 |
| TOGAF | `docs/adr/`：ADR-001~004（框架迁移/Outbox/缓存与读写分离/混合检索），Architecture Repository 治理实践落地 | 文档评审通过 |
| SDD | ADR 与契约门禁互补：决策记录 + AST 强制对齐；schema 按上下文拆分列为下一 DDD 项 | §20 记录 |
| TDD | 本轮全部新增能力先定义验收测试再实现（读路由/幂等/304） | 87 项（+4） |

综合评分：可靠性 7.2→7.5、可扩展性 5.5→6.0、维护性 7.5→7.8；**综合 7.3 → 7.4**。演进：6.1→6.5→6.7→6.9→7.0→7.2→7.3→7.4。

## 21. 七轮落地 + 通往 9.5-10 的实证路径（2026-09-07）

本轮重构：**W3C trace context 传播**（上游 traceparent 保留/派生、响应头贯穿，88 项测试）——可观测性 6.0 → 6.3。**综合 7.4 → 7.5**。

### 21.1 通往 9.5-10：代码侧已尽项与生产实证缺口（诚实边界）

| 分数段 | 性质 | 缺口（不可在本环境生成） |
|---|---|---|
| 7.5（当前） | 代码侧可完成项已基本清偿 | schemas 按上下文拆分（DDD 尾项）、加权限流头 |
| 7.5 → 8.5 | **压测实证** | 目标规模 k6/tiered 压测报告（真实 TiDB/Redis/Pulsar/Milvus 环境）、DB 驱动层 async 化验收、testcontainers 集成测试（Docker 守护进程启动后即执行） |
| 8.5 → 9.5 | **生产运行证据** | 多区域实机部署演练记录、SLO 连续达标面板（30 天）、混沌演练报告、容量-成本曲线 |
| 9.5 → 10 | **认证与审计** | 等保三级测评、CNAS/CMA 依据 GB/T 25000.51 的第三方检测报告、渗透测试报告 |

结论：**代码与工程体系（可迁移部分）已按 9 分段标准建设**；其余分数只能由生产环境证据产生。下一步执行序：① 启动 Docker → testcontainers TiDB 集成测试 → ② 双 Store 合并 → ③ schemas 拆分 → ④ async 驱动 + 压测。
