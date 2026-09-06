# Local Access & Manual Test Guide

> 本文档默认使用 **Colima**（非 Docker Desktop）环境。

## 1) Start local stack

```bash
bash scripts/one_click_shutdown_all.sh
SKIP_BOOTSTRAP_DEPLOY_RUNTIME=true SKIP_BOOTSTRAP_DEV_TOOLCHAIN=true \
  bash scripts/one_click_build_and_deploy.sh local
```

说明：`one_click_build_and_deploy.sh local` 现在会等待控制面与网关就绪后再返回，看到 `[one-click] done` 即可继续。

若出现镜像源网络抖动（SWR/DaoCloud TLS timeout），脚本会自动回退至 docker.io；这是预期行为。

## 2) Direct service access URLs

- Control Plane API: `http://127.0.0.1:8080`
- Go Gateway: `http://127.0.0.1:8090`
- Neo4j Browser: `http://127.0.0.1:7474`
- Milvus endpoint: `http://127.0.0.1:19530`
- Pulsar admin (compose mapping): `http://127.0.0.1:8083`
- TiDB SQL: `127.0.0.1:4000`

### 2.1 局域网团队访问（LAN）

当前 compose 端口映射（如 `8080:8080` / `8090:8090`）已对宿主机网卡开放，可直接通过宿主机 IP 访问。

1. 获取宿主机局域网 IP（示例）

```bash
ipconfig getifaddr en0
```

2. 给测试团队分发以下地址（将 `<HOST_LAN_IP>` 替换为上一步结果）

- Control Plane API: `http://<HOST_LAN_IP>:8080`
- Go Gateway: `http://<HOST_LAN_IP>:8090`
- Neo4j Browser: `http://<HOST_LAN_IP>:7474`

3. macOS 防火墙放通（如已开启防火墙）

- 系统设置 -> 网络 -> 防火墙 -> 允许 Docker/Colima 相关进程接收传入连接。

4. 安全建议（局域网联测强烈建议）

- 不要在空 token 下对整个办公网开放。
- 至少配置 `EKB_AUTH_TOKEN` 并让测试请求携带 `Authorization: Bearer <token>`。
- 仅在测试网段开放端口，不在公网暴露。

> 完整 LAN 联测流程见：`docs/ops/lan-manual-test-playbook.md`

## 3) Quick manual smoke checks

```bash
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8080/healthz
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8080/readyz
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8090/healthz
```

期望：三个接口均返回 `HTTP 200`。

## 4) API manual checks

```bash
curl -sS -X POST http://127.0.0.1:8080/events/relay \
  -H 'Content-Type: application/json' \
  -d '{"batch_size": 20}' \
  -w '\nHTTP %{http_code}\n'

curl -sS -X POST http://127.0.0.1:8080/a2a/publish \
  -H 'Content-Type: application/json' \
  -d '{
    "message_id":"manual-1",
    "correlation_id":"manual-1",
    "tenant_id":"group",
    "region_id":"cn-north-1",
    "agent_id":"planner",
    "target_agent":"executor",
    "intent":"manual_test",
    "priority":"high",
    "idempotency_key":"manual-1",
    "created_at":"2026-04-02T00:00:00Z",
    "ttl_seconds":300,
    "payload":{"k":"v"},
    "metadata":{}
  }' \
  -w '\nHTTP %{http_code}\n'
```

期望：接口返回 `HTTP 200`。

## 5) Replay E2E pressure test

```bash
k6 run perf/k6/replay-e2e-load-test.js
```

说明：该脚本内置严格 SLO 阈值（p95/p99），在开发机本地环境常见“业务成功但阈值未达标”。

通过标准：
- `checks_succeeded` 为 100%
- `http_req_failed` 接近 0（通常 0%）

若需要“只验证功能链路”而不因阈值退出非零，可临时执行：

```bash
k6 run --no-thresholds perf/k6/replay-e2e-load-test.js
```

## 6) Long soak pressure test

```bash
k6 run perf/k6/load-test.js
```

说明：同样受阈值约束；开发机建议先验证功能后再做性能达标评估。

## 7) Teardown

```bash
bash scripts/one_click_shutdown_all.sh
```

## 8) 故障定位（当手工步骤失败时）

```bash
docker compose -f infra/docker-compose.phase3.colima.yml ps
docker compose -f infra/docker-compose.phase3.colima.yml logs --tail=200 ekb-python-control-plane ekb-go-gateway tidb pd tikv
```

若 `8080` 不通，优先检查控制面日志是否出现 `Can't connect to MySQL server on 'tidb'`，这通常表示 TiDB 尚未完全就绪；重新执行第 1 步即可（脚本已内置等待）。

## 9) 分阶段测试与报告

请结合：

- `docs/ops/test-stages-and-reporting-playbook.md`

该文档提供：

- Smoke / Load / Soak / Failover 等分阶段测试策略
- 统一报告模板（执行摘要、SLO 达标、风险、整改闭环）
