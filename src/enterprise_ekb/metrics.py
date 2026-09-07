"""Minimal in-process metrics registry with Prometheus text exposition.

Self-contained by design: the control plane must expose /metrics without
pulling prometheus_client into the runtime image. Counters and summaries are
process-local; for aggregation across replicas scrape each pod (Prometheus
default) rather than sharding state.
"""

from __future__ import annotations

import threading
import time

from enterprise_ekb.logging_setup import new_request_id, request_id_var
from typing import Any, Iterable

# Minimal ASGI typing aliases (avoids a hard dependency on any framework's types).
ASGIApp = Any
Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Any
Send = Any


Labels = dict[str, str] | None


def _label_key(labels: Labels) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted(labels.items()))


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_metric_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _render_labels(label_key: tuple[tuple[str, str], ...]) -> str:
    if not label_key:
        return ""
    joined = ",".join(f'{key}="{_escape_label_value(value)}"' for key, value in label_key)
    return f"{{{joined}}}"


class MetricsRegistry:
    """Thread-safe counters / gauges / count+sum summaries for /metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._observations: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, int]] = {}

    def inc(self, name: str, labels: Labels = None, value: float = 1.0) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, labels: Labels = None, value: float = 0.0) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, labels: Labels = None, value: float = 0.0) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            total, count = self._observations.get(key, (0.0, 0))
            self._observations[key] = (total + value, count + 1)

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            observations = dict(self._observations)

        for (name, label_key), value in sorted(counters.items()):
            safe_name = _escape_metric_name(name)
            lines.append(f"# TYPE {safe_name} counter")
            lines.append(f"{safe_name}{_render_labels(label_key)} {value}")
        for (name, label_key), value in sorted(gauges.items()):
            safe_name = _escape_metric_name(name)
            lines.append(f"# TYPE {safe_name} gauge")
            lines.append(f"{safe_name}{_render_labels(label_key)} {value}")
        for (name, label_key), (total, count) in sorted(observations.items()):
            safe_name = _escape_metric_name(name)
            lines.append(f"# TYPE {safe_name} summary")
            lines.append(f"{safe_name}_count{_render_labels(label_key)} {count}")
            lines.append(f"{safe_name}_sum{_render_labels(label_key)} {total}")
        if lines:
            lines.append("")
        return "\n".join(lines)

    def merge_gauges(self, name: str, samples: Iterable[tuple[Labels, float]]) -> None:
        for labels, value in samples:
            self.set_gauge(name, labels, value)


registry = MetricsRegistry()


class HTTPMetricsMiddleware:
    """Pure-ASGI request metrics middleware (framework-agnostic).

    Works under Litestar, FastAPI/Starlette or any ASGI server. Route-template
    labels come from the framework's routing artifacts in the ASGI scope when
    available; unmatched requests collapse onto a single "unmatched" label so
    attacker-controlled paths cannot explode label cardinality.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") == "/metrics":
            # /metrics is exempt from self-observation: observing the scrape
            # would change the very body it renders (self-referential churn).
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_holder = {"status": 500}
        request_id = new_request_id()
        token = request_id_var.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message.get("type") == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("utf-8")))
                message = dict(message, headers=headers)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            self._observe(scope, 500, started)
            raise
        finally:
            self._observe(scope, status_holder["status"], started)
            request_id_var.reset(token)

    def _observe(self, scope: Scope, status: int, started: float) -> None:
        path = scope.get("path_template") or scope.get("path_format")
        if not isinstance(path, str) or not path:
            route = scope.get("route_handler") or scope.get("litestar.route_handler") or scope.get("route")
            path = getattr(route, "path_format", None) or getattr(route, "path", None)
            if isinstance(path, (tuple, list)):
                path = path[0] if path else None
        if not isinstance(path, str) or not path:
            path = "unmatched"
        registry.observe(
            "ekb_http_request_duration_seconds",
            {"method": str(scope.get("method", "")), "path": path, "status": str(status)},
            time.perf_counter() - started,
        )
