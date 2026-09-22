# EKB 0.8.0-pre 混沌测试报告（2026-09-22）

> 方法论（联网核实）：**Principles of Chaos**（principlesofchaos.org——稳态假设/真实故障注入/爆炸半径最小化/自动化/停止条件）+ **AWS FIS 实验模板模式**（actions/targets/stop conditions）。每实验 = 稳态假设 + 注入 + 停止条件（可用率 <90% 持续 10s 自动中止）+ 恢复 + 稳态复核。
> 实测模式：REAL——真实 LAN 集群（3 副本 control-plane + CRDB 3 节点 Raft）真实注入。
> 原始数据：`docs/chaos/chaos-report-0.7.3.json`（X1-X4）、`docs/chaos/x5-crdb-node-down.json`（X5）。
> 框架：`scripts/chaos_run.py`（可重复执行，自动化原则）。

## 一、实验矩阵与结果（5/5 PASS）

| 实验 | 注入 | 假设 | 注入期可用率 | p50/p95 | RPO | 判定 |
|---|---|---|---|---|---|---|
| X1 pod-kill | 强制删除最旧就绪副本 | 3 副本下可用率≥99%，RTO<30s | **100%**（772 探针） | 1.7/2.2ms | PASS | **PASS** |
| X2 redis-failure | infra/redis service selector 摘除（全部连接失败） | 降级不崩，主链路≥90% | **100%**（1061） | 1.7/2.1ms | PASS | **PASS** |
| X3 pulsar-failure | pulsar-broker selector 摘除 | outbox 积压不丢，恢复追平 | **100%**（1062） | 1.7/2.1ms | PASS | **PASS** |
| X4 cpu-stress | control-plane pod 内 CPU 烧灼（1 核 limit 饱和 40s） | 探针不误杀（0.7.1 修复验证）、降级不崩 | **100%**（964） | 1.7/2.2ms | PASS | **PASS** |
| X5 crdb-node-down | **cockroachdb-c scale=0**（worker1 节点数据面下线 45s） | 3 节点 Raft 仲裁保持（2/3），读写持续 | **100%**（870） | 1.8/2.3ms | PASS | **PASS** |

X1 详细：kill 后 ReplicaSet 自动重建，恢复窗口内无探针失败——与 0.7.3 灾切演练 RTO 10.9s 交叉印证。
X5 详细：CRDB 单节点下线（**高爆炸半径，单点试点**）45 秒期间 max(audits.id) 前后一致（RPO=0），
control-plane 读写全程正常（Raft majority = a+b 两节点）；cockroachdb-c-0 重缩后 56s 内回 Ready。

## 二、发现与修复闭环

1. **X2 首跑注入未生效**（service 名 redis-cluster → 实际 redis）——被 UIM 复核（inject_ok=False）拦截，
   修正后重跑，注入真实生效（期间 L1 pool 自愈/降级路径承接，可用率仍 100%）。**教训：混沌实验的
   "PASS"必须先证明注入真实发生，否则是无效验证。**
2. X4 验证了 0.7.1 的探针修复（timeout 1s→5s）：CPU 单核饱和 40s 无 pod 重启（修复前该场景必现误杀）。
3. 无停止条件触发（5 实验稳态全程未跌破 90%）——系统韧性余量充足；X5 为最严酷注入仍 0 错误。

## 三、与既有证据的互相印证

| 证据链 | 交叉点 |
|---|---|
| DR 演练（0.7.3）RTO 10.9s | X1 pod-kill 同路径重复验证 ✅ |
| RWT 韧性接线（超时/熔断/降级） | X2/X3 依赖故障降级不崩 ✅ |
| DPM 依赖自愈（L1 pool 探活重建） | X2 注入后 48.3s 恢复窗口内无人工干预 ✅ |
| 0.7.1 探针修复 | X4 CPU 饱和无误杀 ✅ |
| CRDB follower reads（ADR-005） | X5 单节点下线读写持续 ✅ |

## 四、未执行项（爆炸半径控制，BRR 铁律）

| 实验 | 状态 | 原因与条件 |
|---|---|---|
| X6 网络分区（pod 间 loss） | 未执行 | 需 chaos-mesh/networkpolix 注入层（当前集群未装），安装属基础设施变更需授权；CLI 替代（tc netem）需特权容器 |
| X7 区域级故障（整节点 drain） | 未执行 | 单节点 LAN 集群 master 上承载 a/b 两 CRDB——drain=双节点下线=仲裁丢失；需 3 节点拓扑（0.8.0 多区阶段） |

两项已列入 scale-plan §七验收门（0.8.0/0.9.0），条件具备即补测。

## 五、评分更新（HSA）

| 维度 | 0.7.3 | 0.8.0-pre | 依据 |
|---|---|---|---|
| 测试真实性 | 9.5 | **9.6** | 混沌 5 实验全 PASS（含 CRDB 节点级高爆炸半径），注入有效性经 UIM 复核 |
| 部署运维 | 9.4 | 9.5 | 混沌框架自动化可重复（Principles ⑥ automation）；停止条件机制落地 |
| **加权总分** | **9.4** | **9.5** | 距 10 剩：灌数 27%→100%、X6/X7（需基础设施演进）、前端深化 |
