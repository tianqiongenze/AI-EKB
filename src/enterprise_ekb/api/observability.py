from __future__ import annotations

import hashlib

from litestar import Request, Response, get

from enterprise_ekb.api.context import ControlPlaneContext
from enterprise_ekb.metrics import registry as metrics_registry


def routes(ctx: ControlPlaneContext) -> list:
    @get("/metrics", include_in_schema=False, sync_to_thread=True)
    def prometheus_metrics(request: Request) -> Response:
        outbox = ctx.store.outbox_stats()
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "pending"}, float(outbox.get("pending", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "processing"}, float(outbox.get("processing", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "dead"}, float(outbox.get("dead", 0)))
        metrics_registry.set_gauge("ekb_outbox_events", {"state": "published"}, float(outbox.get("published", 0)))
        body = metrics_registry.render()
        etag = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
        if request.headers.get("if-none-match") == f'"{etag}"':
            return Response(content=b"", status_code=304)
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4",
            headers={"ETag": f'"{etag}"'},
        )
    return [prometheus_metrics]
