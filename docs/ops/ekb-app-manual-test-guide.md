# EKB 局域网人工测试操作指南（ekb-app 部署环境全流程）

> 本文档是 EKB 在 LAN K8s 集群部署后的**完整人工测试执行手册**，从"前置就绪"到"签收"形成可执行闭环。
> 格式对齐 ESP `docs/test/09-人工测试操作指南.md`（阶段化 / 命令 / 判定 / 不通过处置）；联网对标 Smoke Testing 最佳实践（关键路径优先、curl 快检、冒烟套件 <2 分钟，参考 [RadView](https://www.radview.com)、[TestMu](https://www.testmuai.com)、[OneUptime](https://www.oneuptime.com)）。
> 环境：K8s 集群 10.167.2.175（master）/ 10.167.2.176（worker）；`ekb-app` 命名空间；CRDB 三节点（infra）。
> 预估全程：前置 10min + 冒烟 5min + 功能主测 40min + 治理/事件 20min + 观测验收 10min + 签收 5min ≈ **90 分钟**。
> 日期：2026-09-20。

---

## 〇、入口地址表（测试人员速查）

| 入口 | 地址（集群内任意节点 IP） | 用途 |
|---|---|---|
| **管理台（浏览器）** | `http://10.167.2.175:30881`（或 `:176:30881`） | 四页 + 车间大屏人工功能主测 |
| 控制面 API | `http://10.167.2.175:30880` | curl 冒烟与深度验证 |
| Prometheus 文本指标 | `http://10.167.2.175:30880/metrics` | 观测验收 |
| CRDB Admin UI（只读） | `http://10.167.2.175:30259` | 数据面核查（勿改动 infra） |

> 测试机要求：能访问 10.167.2.0/24 网段 + 任意浏览器 + `curl`（Windows 可用 PowerShell `curl.exe` 或浏览器直开 GET 端点）。

---

## 阶段 0：前置就绪检查（阻塞性，10 分钟）

> 任一 ✗ → 先处置再开工。在 175 上执行（或请运维代执）。

| # | 检查项 | 命令（ssh root@10.167.2.175） | 期望 | ✗ 处置 |
|---|---|---|---|---|
| P-0-1 | 节点就绪 | `kubectl get nodes` | 2 节点 Ready | NotReady → 联系运维 |
| P-0-2 | 控制面双副本 | `kubectl -n ekb-app get deploy ekb-control-plane` | `2/2` | `<2/2` → `kubectl -n ekb-app get pods` 看事件；镜像拉取失败查 registry `curl http://10.100.135.132:5000/v2/_catalog` |
| P-0-3 | 管理台就绪 | `kubectl -n ekb-app get deploy ekb-admin` | `1/1` | 同上 |
| P-0-4 | CRDB 存活 | `kubectl -n infra get pods -l app=cockroachdb-a`（b/c 同理）或 `curl -s http://10.167.2.175:30259/_status/vars \| grep sql_up` | `sql_up 1` | CRDB 挂 → 停止测试上报（infra 为共享设施） |
| P-0-5 | **事务余量（本环境特有）** | `curl -s http://10.167.2.175:30259/_status/vars \| grep "^sql_txns_open{"` | `≤ 2` | **>5 说明有泄漏回归 → 阻断，上报**（CCL 无 license 并发事务上限极低，历史事故见部署报告 §4-2） |
| P-0-6 | 冒烟 | `curl -s http://10.167.2.175:30880/healthz` | `{"status":"ok"}` | 无响应 → NodePort/pod 状态排查 |

---

## 阶段 1：冒烟套件（5 分钟，<2 分钟原则）

在**测试机**（非集群节点）执行，验证网络可达 + 核心链路：

```bash
BASE=http://10.167.2.175:30880
# S-1 存活
curl -s $BASE/healthz                                    # 期望 {"status":"ok"}
# S-2 就绪（数据面真连）
curl -s $BASE/readyz | head -c 200                       # 期望 "status":"ready","db_driver":"crdb"
# S-3 ETag/304 协商（3 次中 ≥2 次 304；连打间隔越短越稳）
ok304=0
for i in 1 2 3; do
  ET=$(curl -s -D- -o /dev/null $BASE/metrics | grep -i '^etag' | tr -d '\r' | cut -d' ' -f2)
  c=$(curl -s -o /dev/null -w "%{http_code}" -H "If-None-Match: $ET" $BASE/metrics)
  [ "$c" = "304" ] && ok304=$((ok304+1))
done; echo "304 hits: $ok304/3"                # 期望 ≥2/3
# 注：后台 relay 每 2s 使计数器跳变，期间返回 200+新 ETag 属正确 HTTP 语义（内容确实变了），
#     不是缺陷；ETag 已做副本稳定化（不含 per-pod 字段）。
# S-4 指标族（随访问路径变化，做过页面操作后更多）
curl -s $BASE/metrics | grep -c "^ekb_"                  # 期望 ≥ 10（活动后典型 25-30）
# S-5 管理台
curl -s -o /dev/null -w "%{http_code}\n" http://10.167.2.175:30881/             # 期望 200
curl -s http://10.167.2.175:30881/api/healthz            # 期望 {"status":"ok"}（代理链路）
```

**判定**：S-1~S-5 全过 → 进入阶段 2；任一失败 → 按阶段 0 处置列排查。

---

## 阶段 2：浏览器功能主测（管理台四页 + 大屏，40 分钟）

> 打开 `http://10.167.2.175:30881`。逐项截图留档。

### 2.1 运行健康页

| # | 步骤 | 期望 | 实测 |
|---|---|---|---|
| F-1 | 首页加载 | 顶部出现「雅迪 EKB 管理台」+ 状态点（ready/事件后端/Outbox 待发数） | |
| F-2 | Outbox 状态卡片 | 显示 pending/processing/published/dead 四计数（JSON） | |
| F-3 | /metrics 卡片 | 出现 `ekb_*` 指标文本 | |
| F-4 | 点击「🌙 暗色」 | 全页切换暗色主题（令牌翻转，无样式错乱） | |
| F-5 | 点击「EN」 | 标题变 "EKB Admin"，页签变英文（i18n） | |
| F-6 | 响应头核查（浏览器 DevTools→Network） | `x-request-id` 与 `traceparent` 存在且每次请求变化 | |

### 2.2 容量估算页

| # | 步骤 | 期望 |
|---|---|---|
| F-7 | 点击「按默认基线估算（10 万在线）」 | 数秒内输出 JSON（estimated_qps 等字段） |
| F-8 | 再点一次 | **结果完全一致**（纯函数缓存命中） |

### 2.3 Skill 治理页（核心业务流）

| # | 步骤 | 期望 |
|---|---|---|
| F-9 | 点击「一键注册并晋级」 | 数秒内显示 `ui-skill-<数字> 已晋级 production ✅`（内部执行注册→review→staging→production 四步） |
| F-10 | 验证策略即时生效 | 用 curl 调 invoke（见 3.1 TC-3，替换 skill 名为上一步显示的名字）期望 `accepted:true` |

### 2.4 审计查询页

| # | 步骤 | 期望 |
|---|---|---|
| F-11 | 点击「查询」 | 返回 JSON（做过 F-9 后 count ≥ 4：注册+三次晋级各一条审计） |

### 2.5 车间大屏页（第 5 页签）

| # | 步骤 | 期望 |
|---|---|---|
| F-12 | 切到「车间大屏」 | 三卡片：Outbox 甜甜圈（published 绿色占主）、Relay 吞吐条形图、运行状态 |
| F-13 | 1080p 全屏（F11） | 布局不破版 |

---

## 阶段 3：API 深度验证（治理面/事件面，20 分钟，curl）

```bash
BASE=http://10.167.2.175:30880
S=mt-$RANDOM            # 本轮测试专属前缀，便于回滚清理
```

### 3.1 治理链路

**TC-1 非法晋级被拒**（状态机门禁）
```bash
curl -s -X POST $BASE/skills/register -H 'Content-Type: application/json' -d "{\"skill_name\":\"$S\",\"version\":\"1.0.0\",\"owner\":\"tester\",\"description\":\"mt\",\"allowed_tools\":[\"tool-a\"],\"allowed_domains\":[\"manufacturing\"],\"residency_scope\":[\"cn-north-1\"],\"risk_level\":\"low\",\"changelog\":\"mt\"}"
# 期望 {"skill":"mt-...","stage":"draft"}
curl -s -X POST $BASE/skills/promote -H 'Content-Type: application/json' -d "{\"skill_name\":\"$S\",\"version\":\"1.0.0\",\"target_stage\":\"production\"}"
# 期望 400 invalid stage transition（draft 不能直达 production）
```

**TC-2 未知工具被策略拒绝**
```bash
for st in review staging production; do curl -s -X POST $BASE/skills/promote -H 'Content-Type: application/json' -d "{\"skill_name\":\"$S\",\"version\":\"1.0.0\",\"target_stage\":\"$st\"}" >/dev/null; done
curl -s -X POST $BASE/mcp/invoke -H 'Content-Type: application/json' -d "{\"tenant_id\":\"group\",\"region_id\":\"cn-north-1\",\"plant_id\":\"p1\",\"user_or_agent_id\":\"mt\",\"skill_name\":\"$S\",\"skill_version\":\"1.0.0\",\"tool_name\":\"tool-NOT-allowed\",\"domain\":\"manufacturing\",\"payload\":{}}"
# 期望 403 tool_not_allowed
```

**TC-3 合法调用放行**（策略缓存命中路径）
```bash
curl -s -X POST $BASE/mcp/invoke -H 'Content-Type: application/json' -d "{\"tenant_id\":\"group\",\"region_id\":\"cn-north-1\",\"plant_id\":\"p1\",\"user_or_agent_id\":\"mt\",\"skill_name\":\"$S\",\"skill_version\":\"1.0.0\",\"tool_name\":\"tool-a\",\"domain\":\"manufacturing\",\"payload\":{}}"
# 期望 {"accepted":true,"reason":"ok",...}
```

### 3.2 事件链路（Outbox → 后台 relay 自动发布）

**TC-4 自动发布时延**
```bash
curl -s -X POST $BASE/flywheel/events -H 'Content-Type: application/json' -d "{\"tenant_id\":\"group\",\"region_id\":\"cn-north-1\",\"plant_id\":\"p1\",\"stage\":\"ingest\",\"objective\":\"mt-$RANDOM\",\"trace_id\":\"mt-trace-$RANDOM$RANDOM\",\"payload\":{\"k\":1}}"
# 期望 {"status":"recorded",...}
sleep 5
curl -s $BASE/readyz | python3 -m json.tool | grep -A5 outbox     # pending 应回 0（2s 轮询 + 余量）
```

**TC-5 域能力幂等重放**
```bash
curl -s -X POST $BASE/domain/capabilities/bootstrap -H 'Content-Type: application/json' -d '{"owner":"mt"}'   # 期望 inserted:36
curl -s -X POST $BASE/domain/capabilities/bootstrap -H 'Content-Type: application/json' -d '{"owner":"mt"}'   # 期望 inserted:36（幂等 upsert，无重复行）
curl -s $BASE/domain/capabilities/coverage                                    # 期望 summary 12/12 met
```

### 3.3 检索与风控

**TC-6 混合检索（lexical 腿）**
```bash
curl -s -X POST $BASE/retrieval/hybrid -H 'Content-Type: application/json' -d '{"tenant_id":"group","region_id":"cn-north-1","query":"quality","top_k":5}'
# 期望 items ≥ 1；legs.lexical ≥ 1；vector/graph 为 0 且 degraded:true（未接外部向量/图客户端，属预期）
```

**TC-7 校验拒绝**
```bash
curl -s -X POST $BASE/retrieval/hybrid -H 'Content-Type: application/json' -d '{"tenant_id":"group","region_id":"cn-north-1"}'
# 期望 400 query_or_vector_required
```

---

## 阶段 4：观测验收（10 分钟）

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| O-1 | 请求时延指标有真实数据 | `curl -s $BASE/metrics \| grep 'ekb_http_request_duration_seconds_count'` | 存在 `/mcp/invoke`、`/retrieval/hybrid` 等本轮测过的路径标签 |
| O-2 | 缓存命中率指标 | `curl -s $BASE/metrics \| grep ekb_cache_hits_total` | F-8 第二次点击后 l1 命中 ≥1 |
| O-3 | relay 指标递增 | `curl -s $BASE/metrics \| grep ekb_outbox_relay_runs_total` | 数值 > 0 且随时间递增 |
| O-4 | CRDB 事务健康 | `curl -s http://10.167.2.175:30259/_status/vars \| grep "^sql_txns_open{"` | 稳定 ≤2（无泄漏） |
| O-5 | 结构化日志 | `ssh root@10.167.2.175 'kubectl -n ekb-app logs deploy/ekb-control-plane --tail=3'` | JSON 行含 `request_id` |

---

## 阶段 5：签收与清理（5 分钟）

### 5.1 Go/No-Go 清单

| 项 | 判定 |
|---|---|
| 阶段 0 全 ✓ + 阶段 1 S-1~S-5 全过 | ☐ |
| F-1~F-13 全过（截图归档） | ☐ |
| TC-1~TC-7 判定符合期望 | ☐ |
| O-1~O-5 全过 | ☐ |
| → 全 ☐ = **GO**（人工测试通过）；任一 ✗ → 记录现象+截图，反馈至 issue |

### 5.2 测试数据清理（可选）

本轮数据（mt- 前缀 skill、flywheel 事件、audits）为集群内测试数据，量小无副作用；如需清理由运维在 CRDB 执行（本指南不提供生产删除 SQL）。

---

## 附 A：常见问题处置

| 现象 | 原因 | 处置 |
|---|---|---|
| 全部 API 500 + CRDB 报 `No license installed...max transactions` | 事务泄漏回归（读路径未 commit） | **阻断上报**；临时缓解：`kubectl -n ekb-app scale deploy/ekb-control-plane --replicas=0` 后再 `--replicas=2` |
| 管理台 200 但 API 卡片报错 | 浏览器直连 30881 但 API 走 `/api` 代理 | 确认使用 30881（非直开 5173）；代理已内置 |
| readyz 显示 `event_backend_mismatch:true` | 配了 pulsar 后端但初始化失败降级 | 当前部署用 InMemory（预期 false）；如见 true 检查 pulsar-broker 可达性 |
| 30880/30881 不通 | NodePort 未放行 | 确认测试机到节点 30000+ 端口段网络策略 |
