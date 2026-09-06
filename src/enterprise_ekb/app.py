"""Control-plane assembler: wires infrastructure into the shared context and
mounts bounded-context route modules onto the Litestar application.

Route handlers live in `enterprise_ekb.api.*` (DDD carrier); this module only
composes them.
"""

from __future__ import annotations

import logging

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
    skills,
    subagent,
)
from enterprise_ekb.api.context import build_context
from enterprise_ekb.config import load_config
from enterprise_ekb.logging_setup import configure_logging
from enterprise_ekb.metrics import HTTPMetricsMiddleware
from enterprise_ekb.risk_control import AntiReplayMiddleware

_logger = logging.getLogger("enterprise_ekb.app")

ROUTE_MODULES = (health, observability, skills, mcp, governance, a2a, subagent, dataops, domain, connectors)


def create_app(db_path: str | None = None) -> Litestar:
    config = load_config()
    configure_logging(config.log_format)
    ctx = build_context(config, db_path)

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
        exception_handlers={ValidationException: _validation_exception_to_422},
    )
    return api


app = create_app()
