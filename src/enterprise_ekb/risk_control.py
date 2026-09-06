"""Risk-control primitives: distributed rate limiting, anti-replay, JWT auth.

Implements the review P0-2/P0-4 funnel: edge signature verification
(HMAC-SHA256 + timestamp window + single-use nonce) and a Redis sliding-window
limiter that degrades to in-memory operation when no Redis backend is
configured, so tests and dev environments run without infrastructure while
production gets cluster-wide correctness.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import threading
import time
from collections import deque
from typing import Any

# Minimal ASGI typing aliases (framework-agnostic, mirrors metrics.py).
ASGIApp = Any
Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Any
Send = Any


# ---------------------------------------------------------------------------
# Distributed rate limiting
# ---------------------------------------------------------------------------

_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local tokens = tonumber(ARGV[3])
local limit = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count + tokens > limit then
    redis.call('PEXPIRE', key, window * 1000)
    return 0
end
for i = 1, tokens do
    local seq = redis.call('INCR', key .. ':seq')
    redis.call('ZADD', key, now, tostring(now) .. '-' .. tostring(seq))
end
redis.call('PEXPIRE', key, window * 1000)
return 1
"""


class _MemorySlidingWindow:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, tokens: int, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) + tokens > limit:
                return False
            for _ in range(tokens):
                hits.append(now)
            return True


class DistributedRateLimiter:
    """Sliding-window limiter keyed per scope+tenant, Redis-backed when given.

    The Redis path is atomic (Lua) so cluster-wide limits are exact across
    replicas; the in-memory fallback keeps semantics per-process for dev/test.
    """

    def __init__(
        self,
        limit_per_window: int,
        window_seconds: int = 60,
        namespace: str = "ekb",
        redis_client: Any | None = None,
    ) -> None:
        self.limit_per_window = limit_per_window
        self.window_seconds = window_seconds
        self.namespace = namespace
        self._redis = redis_client
        self._memory = _MemorySlidingWindow()
        self._script: Any | None = None
        if redis_client is not None:
            try:
                self._script = redis_client.register_script(_SLIDING_WINDOW_LUA)
            except Exception:
                self._redis = None

    def allow(
        self,
        key: str,
        tokens: int = 1,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> bool:
        effective_limit = limit if limit is not None else self.limit_per_window
        effective_window = window_seconds if window_seconds is not None else self.window_seconds
        if self._redis is not None and self._script is not None:
            try:
                result = self._script(
                    keys=[f"{self.namespace}:rl:{key}"],
                    args=[int(time.time()), effective_window, tokens, effective_limit],
                )
                return int(result) == 1
            except Exception:
                # Backend failure must not take the control plane down: fall back
                # to the in-memory window (per-process) until Redis recovers.
                pass
        return self._memory.allow(key, tokens, effective_limit, effective_window)


# ---------------------------------------------------------------------------
# Anti-replay: HMAC signature + timestamp window + single-use nonce
# ---------------------------------------------------------------------------


class NonceStore:
    """Single-use nonce registry: Redis SET NX EX when available, else memory."""

    def __init__(self, ttl_seconds: int, redis_client: Any | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self._redis = redis_client
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def _memory_put_if_absent(self, nonce: str) -> bool:
        now = time.monotonic()
        with self._lock:
            for key in [k for k, exp in self._seen.items() if exp <= now]:
                self._seen.pop(key, None)
            if nonce in self._seen:
                return False
            self._seen[nonce] = now + self.ttl_seconds
            return True

    def put_if_absent(self, nonce: str) -> bool:
        if self._redis is not None:
            try:
                stored = self._redis.set(f"ekb:nonce:{nonce}", b"1", nx=True, ex=self.ttl_seconds)
                return bool(stored)
            except Exception:
                pass
        return self._memory_put_if_absent(nonce)


def compute_signature(
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    mac = hmac.new(
        secret.encode("utf-8"),
        "\n".join(
            [
                method.upper(),
                path,
                timestamp,
                nonce,
                hashlib.sha256(body).hexdigest(),
            ]
        ).encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


class AntiReplayMiddleware:
    """Pure-ASGI HMAC anti-replay guard for POST bodies on guarded prefixes.

    Pass-through (zero overhead) unless a signing secret is configured. On
    failure it answers directly with 401 and a JSON detail — it does not rely
    on framework exception translation.
    """

    GUARDED_PREFIXES = ("/mcp/", "/a2a/", "/connectors/")

    def __init__(
        self,
        app: ASGIApp,
        secret: str = "",
        window_seconds: int = 300,
        nonce_store: NonceStore | None = None,
        guarded_prefixes: list[str] | None = None,
    ) -> None:
        self.app = app
        self.secret = secret
        self.window_seconds = window_seconds
        self.nonce_store = nonce_store or NonceStore(ttl_seconds=window_seconds)
        self.guarded_prefixes = guarded_prefixes or list(self.GUARDED_PREFIXES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or not self.secret:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        method = str(scope.get("method", "")).upper()
        guarded = method == "POST" and any(path.startswith(p) for p in self.guarded_prefixes)
        if not guarded:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        timestamp = headers.get("x-ekb-timestamp", "")
        nonce = headers.get("x-ekb-nonce", "")
        signature = headers.get("x-ekb-signature", "")

        body = b""
        complete = False
        while not complete:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            complete = not message.get("more_body", False)

        error = self._verify(method, path, timestamp, nonce, signature, body)
        if error is not None:
            await self._reject(send, error)
            return

        async def replay_body() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_body, send)

    def _verify(
        self, method: str, path: str, timestamp: str, nonce: str, signature: str, body: bytes
    ) -> str | None:
        if not timestamp or not nonce or not signature:
            return "signature_headers_missing"
        try:
            request_time = int(timestamp)
        except ValueError:
            return "timestamp_invalid"
        if abs(time.time() - request_time) > self.window_seconds:
            return "timestamp_out_of_window"
        expected = compute_signature(self.secret, method, path, timestamp, nonce, body)
        if not hmac.compare_digest(signature, expected):
            return "signature_invalid"
        if not self.nonce_store.put_if_absent(f"{timestamp}:{nonce}"):
            return "replay_detected"
        return None

    async def _reject(self, send: Send, detail: str) -> None:
        payload = json.dumps({"detail": detail, "status_code": 401}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": payload})


# ---------------------------------------------------------------------------
# Bearer credential verification: static token (constant-time) + JWT
# ---------------------------------------------------------------------------


def verify_bearer_credential(
    auth_header: str,
    static_token: str,
    jwt_hs256_secret: str = "",
    jwt_expected_audience: str = "",
) -> bool:
    """True when the Authorization header carries a valid credential.

    Static tokens are compared in constant time; JWTs (two dots) are verified
    with HS256 when a secret is configured, honouring exp/nbf and — when set —
    the expected audience.
    """
    if not auth_header.startswith("Bearer "):
        return False
    presented = auth_header[len("Bearer "):]
    if static_token and hmac.compare_digest(presented, static_token):
        return True
    if presented.count(".") == 2 and jwt_hs256_secret:
        return _verify_jwt(presented, jwt_hs256_secret, jwt_expected_audience)
    return False


def _verify_jwt(token: str, secret: str, expected_audience: str) -> bool:
    try:
        jwt_module = importlib.import_module("jwt")
    except ImportError:
        return False
    try:
        options = {"require": ["exp"]}
        audience = expected_audience or None
        jwt_module.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            options=options,
        )
        return True
    except Exception:
        return False
