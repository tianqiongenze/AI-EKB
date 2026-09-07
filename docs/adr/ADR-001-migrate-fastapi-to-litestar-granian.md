# ADR-001: 控制面 Web 框架从 FastAPI 迁移至 Litestar + Granian

- 状态：accepted（2026-09）
- 背景：全同步 handler + Starlette 线程池模型与"100 万并发"目标存在代差；契约门禁与 62 项测试构成安全网。
- 决策：迁移至 Litestar 2.24（保留参数名 request/data、类型化路径参数、sync_to_thread 显式化）+ Granian（Rust HTTP 服务器）；POST 200/校验 422 契约零漂移；校验错误自定义 handler 保持 422。
- 后果：全异步 ASGI 就绪；契约门禁升级为双风格识别；DB 驱动层 async 化（aiosqlite/asyncmy）留待压测环境（ADR-004）。
