# LAN Manual Testing Playbook

> 目标：将本地 Colima 一键部署环境稳定共享给同一局域网测试团队，进行多人并行人工测试。

## 1. 适用范围

- 单台开发机作为临时联测主机
- 测试团队与主机在同一局域网
- 非公网暴露场景

## 2. 联测前检查（主机）

1) 启动并确认服务就绪

```bash
bash scripts/one_click_shutdown_all.sh
SKIP_BOOTSTRAP_DEPLOY_RUNTIME=true SKIP_BOOTSTRAP_DEV_TOOLCHAIN=true \
  bash scripts/one_click_build_and_deploy.sh local
```

2) 获取局域网 IP

```bash
ipconfig getifaddr en0
```

3) 本机健康检查

```bash
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8080/healthz
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8080/readyz
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8090/healthz
```

## 3. 提供给测试团队的访问入口

将 `<HOST_LAN_IP>` 替换为主机 IP：

- Control Plane: `http://<HOST_LAN_IP>:8080`
- Go Gateway: `http://<HOST_LAN_IP>:8090`
- Neo4j Browser: `http://<HOST_LAN_IP>:7474`

## 4. 安全基线（强制）

1) 最低要求

- 联测阶段必须配置鉴权 token（`EKB_AUTH_TOKEN`），禁止长期空 token。
- 仅在内网测试网段开放端口。

2) 网络边界

- 禁止将本机端口映射到公网。
- 如主机启用防火墙，仅放通测试网段。

3) 数据安全

- 使用脱敏测试数据，不导入生产真实敏感数据。

## 5. 团队人工测试分工建议

- 接口功能组：按 `manual-test-access-guide.md` 执行 healthz/readyz 与关键 API 用例
- 稳定性组：执行 replay 与轻量并发验证
- 兼容性组：不同浏览器/终端并发访问
- 记录组：统一收集失败请求、时间窗口、日志片段

## 6. 常见问题

### Q1: 团队成员无法访问 `<HOST_LAN_IP>:8080`

- 检查主机防火墙是否阻断
- 检查成员是否在同一子网
- 检查服务是否仍为 `HTTP 200`

### Q2: 局域网下偶发超时

- 先看 `docker compose ... logs`
- 若仅性能长尾，优先记录并纳入性能报告，不直接判定功能失败

## 7. 联测结束

```bash
bash scripts/one_click_shutdown_all.sh
```
