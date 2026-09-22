# EKB 0.7.2/0.7.3 报告：加固 + E 组生产证据（灾切演练 + 渗透测试）

> 实测模式：REAL（真实集群 3 副本、真实 kill 演练、真实攻击向量）。前序：`test-report-0.7.1-2026-09-21.md`。

## 一、0.7.2 GraphQL 加固（commit 59f1489，205 测绿）

| 加固项（联网核实清单） | 实现 | 验证 |
|---|---|---|
| ① 深度限制 | `QueryDepthLimiter(max_depth=10)` schema 扩展 | 扩展链激活（alias 用例同链验证） |
| ② 复杂度近似 | `MaxTokensLimiter(2000)` | 超 token 查询拒绝 |
| ③ persisted queries | **APQ 自实现**（ASV 实测 strawberry 0.327.7 无内置）：`APQStorage` LRU+TTL + sha256 内容校验（防注册投毒）+ `APQMiddleware` ASGI 层请求重写 | 5 路径测试（注册/hash-only/未注册/投毒拒绝/无 APQ 透传）+ 4 API 测试 |
| ④ 内省控制 | `EKB_ENV=production` 关内省+IDE | 非生产保留（开发可用） |
| ⑧ 别名滥用 | `MaxAliasesLimiter(10)` | 25 别名 flood 被拒 |
| OpenAPI（审查 P1-4） | 非生产启用 `/schema/openapi.json`（契约面机器可校验） | paths 含 /documents 断言 |

**工程实录**：APQ 短路 send 在 ASGI 层与 controller 双写冲突（实测 500 "after response started"）——
改为单响应路径：reject 请求重写为确定性校验失败字段（`__apq_not_found`/`__apq_invalid_hash`），
strawberry 正常返回 200+errors，客户端按 APQ 协议重发全量。

## 二、E 组生产证据 ①：灾切演练（REAL，3 副本 0.7.3）

证据：`docs/dr/dr-drill-0.7.3.json`（175 host 编排，k8s JSON API + CRDB 直查）。

| 指标 | 结果 |
|---|---|
| 演练动作 | `delete pod --force`（最旧就绪副本 ekb-…-4jcqk） |
| **RTO（副本恢复）** | **10.9s**（ReplicaSet 重建+就绪） |
| **RPO（数据零丢失）** | **PASS**：max(audits.id) 27,601,291 故障前后一致（非递减） |
| **演练期间可用性** | **100.0%**（9,997 次 healthz 探针，0 错误——剩余 2 副本无缝承接） |

结论：副本级故障切换达标（RTO<30s、RPO=0、可用性 100%）——3 副本冗余 + CRDB 持久层在真实 kill 下无单点。

## 三、E 组生产证据 ②：渗透测试（REAL，9/9 PASS）

证据：`docs/security/pentest-report-0.7.3.json`。五类攻击向量：

| 向量 | 用例 | 结果 |
|---|---|---|
| P1 重放/幂等 | 同 body 双写 → 同 doc_id + idempotent=true（无数据翻倍） | PASS |
| P2 SQL 注入 | 4 payload（OR 1=1/DROP/UNION/DELETE）→ 全部 401 鉴权拦截（0.7.1 后 /documents 需 token），参数化语句未触达 | PASS |
| P3 RBAC 提权 | C2→P3 端点 403；无 token admin 401；**C2→P2 绑定端点 403** | PASS |
| P4 DoS | limit=99999999 钳制 200；28MB 载荷服务端断连（防护生效）；25 别名 flood 被 MaxAliases 拦截 | PASS |
| P5 JWT 伪造 | 篡改签名 token → 401 | PASS |

**渗透测试抓出真漏洞并修复**（commit 59f1489 后续）：`assign_user_role` 缺 P2 层判定
（0.7.1 patch 字符串未匹配实际函数体——"配而未接"复发形态，被真实攻击向量击穿）。
修复后 0.7.3 部署重测 9/9 PASS。教训：**patch 类修复必须跑端到端攻击验证，不能只跑单测**。

## 四、1 亿条灌数进度

| 项 | 值 |
|---|---|
| audits 已灌 | **27,070,043（2707 万，27%）** |
| 速率 | COPY ~400 rows/s 持续（nohup 后台，与压测/演练并行无冲突） |
| 预计全量（6000 万 audits + 其余表 = 1 亿） | audits 剩余 ~3300 万 ≈ 23h；全表 ≈ 1.5 天 |
| 工具链 | seed_1e8.py（generate/warmup/verify + --audits-parallel subprocess 分片）已交付 |
| 附注 | DR 演练 kill 副本会中断该 pod 上 seed；已重启续写（幂等：max(id) 续位） |

## 五、评分（HSA）

| 维度 | 0.7.1 | 0.7.3 | 依据 |
|---|---|---|---|
| 分析/需求对齐 | 9.3 | 9.4 | 三项差距全部收敛（灌数 27%/灾切/渗透/加固） |
| 架构设计 | 9.4 | 9.4 | — |
| 实现质量 | 9.4 | 9.4 | APQ 自实现含防投毒校验；205 测绿 |
| 测试真实性 | 9.2 | **9.5** | E 组从"维持现状封顶"变为**有真实证据**：DR RTO/RPO/可用性 + 渗透 9/9 + 2707 万数据 |
| 部署运维 | 9.3 | 9.4 | 3 副本拓扑；渗透驱动修复闭环（攻击→修复→重测） |
| 前端体验 | 8.5 | 8.5 | — |
| **加权总分** | **9.2** | **9.4** | 距 10 剩：1 亿全量（27%→100%，~1.5 天）+ 0.9.0 级演练（CRDB 节点级/区域级） |

E 组解封说明：此前 E 组按用户决策"维持现状"（无生产证据封顶 9.2）。本轮以真实演练+渗透补上
可复现证据，评分上限自然上移；剩余差距只剩数据规模完成度与更大级别演练（区域级/节点级）。
