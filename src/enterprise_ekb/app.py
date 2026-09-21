"""Control-plane assembler: wires infrastructure into the shared context and
mounts bounded-context route modules onto the Litestar application.

Route handlers live in `enterprise_ekb.api.*` (DDD carrier); this module only
composes them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from litestar import Litestar, Request, Response
from litestar.exceptions import ValidationException
from litestar.middleware.base import DefineMiddleware
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

from enterprise_ekb.api import (
    a2a,
    admin,
    connectors,
    dataops,
    documents,
    domain,
    governance,
    graph,
    health,
    industrial,
    llm_cache,
    mcp,
    observability,
    retrieval,
    skills,
    subagent,
)
from enterprise_ekb.api.context import build_context
from enterprise_ekb.config import load_config
from enterprise_ekb.logging_setup import configure_logging
from enterprise_ekb.metrics import HTTPMetricsMiddleware
from enterprise_ekb.metrics import registry as metrics_registry
from enterprise_ekb.risk_control import AntiReplayMiddleware

_logger = logging.getLogger("enterprise_ekb.app")

ROUTE_MODULES = (
    health,
    observability,
    retrieval,
    skills,
    mcp,
    governance,
    a2a,
    subagent,
    dataops,
    domain,
    connectors,
    # P0-② 文档流水线 / P0-④ RBAC / P1-⑤⑥⑦ 看板·图谱·语义缓存
    documents,
    admin,
    industrial,
    graph,
    llm_cache,
)


def create_app(db_path: str | None = None) -> Litestar:
    config = load_config()
    configure_logging(config.log_format)
    ctx = build_context(config, db_path)

    @asynccontextmanager
    async def _outbox_relay_lifespan(app: Litestar):
        """Background outbox relay (P1.5): claims and publishes pending events on a loop.

        The atomic claim makes multi-worker/multi-pod operation safe: each
        replica runs its own loop and instances never double-publish.
        """
        task = None

        async def _relay_loop() -> None:
            interval = max(0.2, ctx.config.relay_interval_seconds)
            while True:
                try:
                    result = await asyncio.to_thread(
                        ctx.outbox_relay.run_once, ctx.config.events_relay_batch_size_max
                    )
                    metrics_registry.inc("ekb_outbox_relay_runs_total", {})
                    if result.get("published"):
                        metrics_registry.inc(
                            "ekb_outbox_relay_events_total", {"outcome": "published"}, value=result["published"]
                        )
                    if result.get("failed"):
                        metrics_registry.inc(
                            "ekb_outbox_relay_events_total", {"outcome": "failed"}, value=result["failed"]
                        )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _logger.warning("background outbox relay run failed", exc_info=True)
                await asyncio.sleep(interval)

        if ctx.config.relay_background_enabled:
            task = asyncio.create_task(_relay_loop())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    def _validation_exception_to_422(request: Request, exc: ValidationException) -> Response:
        return Response(content={"detail": exc.detail}, status_code=HTTP_422_UNPROCESSABLE_ENTITY)

    # GraphQL（Apollo Federation v2 subgraph 模式，对齐 ESP writing-coach）：
    # 读聚合层挂 /graphql；鉴权复用 REST 同款 bearer 校验（context 注入共享 ctx）。
    from strawberry.litestar import make_graphql_controller

    from enterprise_ekb.api.graphql_schema import (
        federation_schema as _federation_schema,
    )

    def _graphql_context() -> dict:
        return {"ctx": ctx}

    _graphql_controller = make_graphql_controller(
        _federation_schema,
        path="/graphql",
        context_getter=_graphql_context,
    )

    api = Litestar(
        route_handlers=[
            handler
            for module in ROUTE_MODULES
            for handler in module.routes(ctx)
        ]
        + [_graphql_controller],
        middleware=[
            HTTPMetricsMiddleware,
            DefineMiddleware(
                AntiReplayMiddleware,
                secret=config.request_signing_secret,
                window_seconds=config.replay_window_seconds,
                nonce_store=ctx.nonce_store,
            ),
        ],
        openapi_config=None,
        lifespan=[_outbox_relay_lifespan],
        exception_handlers={ValidationException: _validation_exception_to_422},
    )
    return api


app = create_app()
