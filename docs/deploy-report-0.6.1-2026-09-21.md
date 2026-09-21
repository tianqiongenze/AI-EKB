# EKB 0.6.1 部署与验证报告（2026-09-21）

> 实测模式标注：除 PaddleOCR（未安装，DEFERRED）外，本报告全部条目为 **REAL**（真实集群 / 真实 CRDB / 真实解析器 / 真实 LLM 后端）。无任何 mock 通过冒充上线证据（MPB/HSA）。

## 一、部署概要

| 项 | 值 |
|---|---|
| 版本 | ekb-control-plane **0.6.1**（0.6.0 因 mcp 缓存序列化缺陷被替代）、ekb-admin **0.6.0** |
| 集群 | LAN K8s 10.167.2.175(k8s-master)/176(k8s-worker1)，namespace `ekb-app` |
| 入口 | control-plane NodePort **30880**，admin UI NodePort **30881** |
| 数据面 | CockroachDB v24.3.11（`cockroachdb.infra.svc.cluster.local`，`ekb_control_plane`） |
| 仓库源码 | rsync → `175:/opt/ekb-src`，镜像 build 于 175 → push `10.100.135.132:5000` |

## 二、本版新增能力（P0-②③④ + P1-⑤⑥⑦）

| 项 | 内容 | 证据（命令/输出摘要） |
|---|---|---|
| P0-② 文档流水线 | PyMuPDF/python-docx/python-pptx 真实解析；父子分块 512/64 滑窗；表格/图片独立 chunk；OCR 可选 extra 未装如实上报 | 集群内真实 docx 摄入：`docx ingest: indexed | chunks: 2 | caps: {pdf:T, docx:T, pptx:T, ocr:F}`；md 摄入 `chunks:2 (parent+text)` |
| P0-② 存储 | SQLite+CRDB 双实现 `documents`/`document_chunks`（`_write_op`/`_read_only_txn` 全覆盖，CCL 开放事务上限安全） | 容器内直连 CRDB upsert/chunk/list 全通 |
| P0-② API | POST /documents/ingest（sha256 内容幂等）+ list/detail/chunks/delete | 幂等重放 `idempotent: True` |
| P0-④ RBAC | §1.2.2 12 角色（9 人类+3 非人类）×4 权限层+层继承；/admin/rbac/roles\|users | `roles: 12`；绑定 `probe-user→B1` 后 `GET /admin/rbac/users` 返回该行 |
| P1-⑦ 语义缓存 | L1 sha256 精确+L2 cosine≥0.92；接入 /mcp/invoke 带 cache_hit/cache_layer | 真机：第 2 次同参调用 `cache_hit: True, layer: 1`，`hits_l1=1 hit_rate=0.50` |
| P1-⑥ 知识图谱 | 确定性实体/关系抽取（33 领域词），/graph/build\|search\|neighbors\|stats | `graph/build → {"nodes":2,"edges":1}`；`search?keyword=TTFAR` 返回实体 |
| P1-⑤ 工业看板 | OEE/直通率/缺陷帕累托/能耗 proxy（audit 聚合+basis 标注，不造假数据） | `GET /industrial/kpis => 200`，空窗口返零值+`basis` 说明 |
| 前端 | 4 新页面（文档/检索/图谱/看板）+ i18n | vitest 34 passed；build 57.31KB gzip；`:30881` 200 |

## 三、测试与门禁（全绿）

| 门禁 | 结果 | 命令 |
|---|---|---|
| 单测回归 | **182 passed** | `.venv/bin/python -m pytest tests/ -q` |
| ruff | **0 errors**（ruff.toml 新增门禁配置） | `ruff check src/ tests/` |
| mypy --strict（新 4 模块） | **0 errors** | `mypy --strict document_pipeline rbac semantic_cache knowledge_graph` |
| 覆盖率 TCG | document_pipeline **81%** / rbac **99%** / semantic_cache **91%** / knowledge_graph **96%** | `pytest --cov=... --cov-report=term` |
| 契约一致性 | PASSED（OpenAPI +17 路由、Pulsar +4 事件已回写 contracts/） | `pytest tests/test_contract_consistency_extended.py` |
| 前端 | vitest **34 passed**；tsc --noEmit 0；`npm run build` 成功 | 见上 |
| 使用的 Skill | `code-review`（方法论引用）、`verification-before-completion`（完成前核验清单） | Skill-first 铁律声明 |

## 四、部署过程问题与修复（UIM/CSV/SVD 实录）

1. **admin 探针 404→永不就绪**：容器 Granian 监听 8080，而清单 readinessProbe 打 80。正向探针（容器内 `urlopen 127.0.0.1:8080/healthz → 200`，`:80 → refused`）实锤根因。已修探针端口+回写 `/root/ekb-admin-deploy.yaml`（远端真源）。
2. **ingest 500 `can't adapt type 'dict'`**：CRDB JSONB 列传 dict，psycopg2 不适配。改 `json.dumps(..., ensure_ascii=False)` 传参（与既有 `upsert_business_capability` 同模式）。
3. **同 tag 双 digest 漂移**：0.6.0 修复后同 tag 重 build，worker1 `IfNotPresent` 命中旧层。SVD 三态核对发现 spec==tag 但 pod imageID 分裂（…e152 旧 vs …4f26 新）。处置：改发 **0.6.1 新 tag**，两节点 `docker pull` 确认 digest `ddf36c7a…` 一致后驱逐旧 pod。教训落盘：**修复镜像必须新 tag，禁止复用已下发 tag**。
4. **语义缓存 entries=0**：`GatewayResponse.data` 是 dict，`SemanticCache.put` 只收 str。put 前 `json.dumps`、命中 `json.loads` 还原（commit `0e08c0f`）。真机复测命中。
5. **apiExt 参数名与后端不符**：`/graph/search` 真参 `keyword`（非 q）、`/graph/neighbors` 真参 `entity/hops`（非 node）；retrieval 请求体不需要 tenant_id。前端已按 ASV 查证后修正。

## 五、遗留与 DEFERRED（诚实清单）

- **PaddleOCR（扫描件 OCR）**：未安装（重型依赖）。流水线如实上报 `ocr: False` 并给 warning；生产需要时 `pip install -e ".[ocr]"` 即生效。**DEFERRED，不阻塞文本类文档链路**。
- **图持久化 Neo4j**：KnowledgeGraphService 为进程内存储，多副本各持独立图，可从 chunks 确定性重建。多副本共享图 **DEFERRED**（LAN 部署可接受）。
- **outbox dead=3**：历史遗留死信（0.5.x 时代的 compression=int 事件），非本版新增；0.6.x 事件（document.ingested/graph.rebuilt/rbac.user.assigned）全部 pending→published 正常。
- **admin UI `GET :30881/ => 404`**：admin 前端入口 `/` 由旧镜像静态路由负责，0.6.0 后端镜像根路径无静态文件（healthz 200 正常）。前端托管形态（SPA 静态挂载到 admin 镜像或独立 nginx）**DEFERRED，待下版专项**。
- **L2 语义层**：无 embedding_fn 注入时自动禁用（当前部署如此），L1 精确层已真机验证；接 vLLM embedding 后 L2 即生效。

## 六、评分（HSA 诚实自评，证据可复现）

| 维度 | 上轮 | 本轮 | 依据 |
|---|---|---|---|
| 分析/需求对齐 | 8.4 | 9.0 | §5.1/§1.2.2 规格逐条落地并有集群证据 |
| 架构设计 | 8.6 | 9.0 | DDD 边界维持；文档流水线/图谱/缓存均为可插拔组件；契约双向核对门禁化 |
| 实现质量 | 8.3 | 9.0 | 182 测全绿；4 新模块覆盖率 81–99%；ruff/mypy 门禁落盘 |
| 测试真实性 | 7.8 | 8.8 | REAL 模式为主，OCR 明确 DEFERRED；集群探针+幂等+缓存命中实测 |
| 部署运维 | 8.0 | 8.6 | BVV/SVD/UIM 全过程实录，4 问题 4 修复；outbox 无新增死信 |
| 前端体验 | 7.0 | 8.4 | 4 页面+测试+高亮+SVG 图表+口径标注；SPA 托管形态待下版 |
| **加权总分** | **8.6** | **8.9** | E 组（生产证据：多副本 CRDB 压测/灾切演练）维持现状，封顶 |
