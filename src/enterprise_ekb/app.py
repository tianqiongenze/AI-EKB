"""Control-plane assembler: wires infrastructure into the shared context and
mounts bounded-context route modules onto the Litestar application.

Route handlers live in `enterprise_ekb.api.*` (DDD carrier); this module only
composes them.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from litestar import Litestar, Request, Response
from litestar.exceptions import ValidationException
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY
from litestar.middleware.base import DefineMiddleware

from enterprise_ekb.api import (
    a2a,
    connectors,
    dataops,
    domain,
    governance,
    health,
    mcp,
    observability,
    retrieval,
    skills,
    subagent,
)
from enterprise_ekb.api.context import build_context
from enterprise_ekb.config import load_config
from enterprise_ekb.logging_setup import configure_logging
from enterprise_ekb.metrics import HTTPMetricsMiddleware, registry as metrics_registry
from enterprise_ekb.risk_control import AntiReplayMiddleware

_logger = logging.getLogger("enterprise_ekb.app")

ROUTE_MODULES = (health, observability, retrieval, skills, mcp, governance, a2a, subagent, dataops, domain, connectors)


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
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    def _validation_exception_to_422(request: Request, exc: ValidationException) -> Response:
        return Response(content={"detail": exc.detail}, status_code=HTTP_422_UNPROCESSABLE_ENTITY)

    api = Litestar(
        route_handlers=[
            handler
            for module in ROUTE_MODULES
            for handler in module.routes(ctx)
        ],
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
