# Test Stages and Reporting Playbook

> 目标：建立统一的“分阶段测试 -> 量化结论 -> 风险闭环”机制，支撑从本地验证走向生产级高可用与高并发。

## 1. 测试阶段定义

### Stage A — Smoke（功能冒烟）

目的：验证服务可用与核心链路可执行。

建议命令：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
curl http://127.0.0.1:8090/healthz
```

准入标准：关键接口全部 HTTP 200。

### Stage B — Replay（业务链路回放）

目的：验证真实请求结构下的功能正确性与错误率。

建议命令：

```bash
k6 run perf/k6/replay-e2e-load-test.js
```

在开发机可使用：

```bash
k6 run --no-thresholds perf/k6/replay-e2e-load-test.js
```

准入标准：`checks_succeeded` 接近/达到 100%，`http_req_failed` 接近 0。

### Stage C — Load（容量压测）

目的：验证 Ramp/Spike 下系统容量与退化行为。

建议命令：

```bash
k6 run perf/k6/load-test.js
```

准入标准：达到预设 SLO 阈值（p95/p99、失败率、吞吐）。

### Stage D — Soak（长稳压测）

目的：验证长时间稳定性（连接泄露、队列积压、性能漂移）。

建议：延长 soak 持续时长并保留完整指标与日志。

准入标准：错误率无持续上升趋势，队列/积压可控。

### Stage E — Failover/DR（容灾演练）

目的：验证故障切换与恢复目标（RTO/RPO）可达成。

准入标准：

- 切换流程可执行
- RTO/RPO 达标
- 形成演练报告与整改计划

## 2. 报告模板（每阶段通用）

## 2.1 执行摘要

- 测试阶段：
- 测试时间窗口：
- 测试环境（硬件/网络/部署方式）：
- 结论（通过/有条件通过/不通过）：

## 2.2 关键指标

- 请求总量：
- 错误率（http_req_failed）：
- 延迟（p50/p95/p99）：
- 吞吐（RPS）：
- 资源占用（CPU/内存/连接数）：

## 2.3 异常与根因

- 异常现象：
- 影响范围：
- 根因定位：
- 证据（日志/指标/请求样例）：

## 2.4 整改与回归计划

- 修复项：
- 责任人：
- 计划完成时间：
- 回归验证方式：

## 2.5 风险评估

- 当前残余风险：
- 上线前阻断项（Blockers）：

## 3. 版本化留档建议

建议按日期留档：

- `docs/reports/YYYY-MM-DD-stageA-smoke.md`
- `docs/reports/YYYY-MM-DD-stageB-replay.md`
- `docs/reports/YYYY-MM-DD-stageC-load.md`
- `docs/reports/YYYY-MM-DD-stageD-soak.md`
- `docs/reports/YYYY-MM-DD-stageE-dr.md`

并附带：

- k6 原始输出（json/summary）
- 关键日志摘录
- dashboard 截图（如有）

## 4. P0→P3 工程化执行入口

新增可执行入口：

- `scripts/seed_large_scale_data.py`（1M+ 多存储造数）
- `scripts/benchmark_store_operations.py`（数据库/缓存性能基准）
- `scripts/run_capacity_ha_gates.py`（分阶段 gate 执行）

建议执行顺序：

1. `P0`：先跑回归与现有 SLO 脚本门禁
2. `P1`：完成 1M 造数 + 存储基准 + replay 功能压测
3. `P2`：执行长压测并形成 load 报告
4. `P3`：校验 DR/架构文档与证据完备性

参考文档：`docs/ops/p0-p3-capacity-ha-implementation.md`
