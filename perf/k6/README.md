# k6 SLO 压测说明

## 1. 目标

验证 API Gateway + AI 控制面二期链路在以下场景下是否满足 SLO：

- Ramp-up / Ramp-down
- Spike
- Soak

## 2. 默认阈值

- `http_req_failed < 0.2%`
- `gateway.latency p95 < 250ms, p99 < 500ms`
- `ai_control.latency p95 < 500ms, p99 < 1200ms`

## 3. 运行方法

```bash
k6 run perf/k6/load-test.js
```

或指定目标地址：

```bash
BASE_URL=http://localhost:8080 k6 run perf/k6/load-test.js
```

## 4. 场景结构

- ramp_up：逐步升压，验证扩缩容与基础稳定性
- spike：短时突发，验证熔断、限流与恢复能力
- soak：长稳压，验证内存、连接池与性能漂移
