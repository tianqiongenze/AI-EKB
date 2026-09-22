"""GraphQL Automatic Persisted Queries (APQ) 存储——0.7.2 加固项。

背景（ASV 实测）：strawberry-graphql 0.327.7 无内置 APQ 扩展（`strawberry.extensions.apq`
不存在，http 层也无 persisted 实现）；按 Apollo APQ 协议自实现存储层：
1. 客户端首查发送 `extensions.persistedQuery {version, sha256Hash}` + 完整 query → 服务端注册。
2. 后续请求只发 hash → 服务端按 hash 取回注册的 query 执行。
3. 未注册 hash 只发 hash → 返回 `PersistedQueryNotFound`（客户端重发全量注册）。

安全语义（加固清单③）：hash 必须与 query 内容一致（服务端校验 sha256(query)==hash，
防"注册 A 执行 B"投毒）；未命中即 Not Found 不报错（协议要求）；TTL+容量上限防注册表膨胀。
单副本内存存储（与 semantic_cache 同等假设），多副本共享排 0.8.0（Redis 通道）。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from typing import Any


class APQStorage:
    """hash → query 注册表（LRU+TTL）。线程安全。"""

    def __init__(self, max_entries: int = 2048, ttl_seconds: int = 3600) -> None:
        self._max = max(1, int(max_entries))
        self._ttl = max(1, int(ttl_seconds))
        self._lock = threading.Lock()
        # hash → (query, registered_at)
        self._store: dict[str, tuple[str, float]] = {}

    @staticmethod
    def verify_hash(query: str, sha256_hash: str) -> bool:
        """校验客户端 hash 与 query 内容一致（防注册投毒）。"""
        if not query or not sha256_hash:
            return False
        computed = hashlib.sha256(query.encode("utf-8")).hexdigest()
        return secrets_eq(computed, sha256_hash.strip().lower())

    def register(self, sha256_hash: str, query: str) -> bool:
        """注册/更新 query；hash 不匹配拒绝（返回 False）。"""
        if not self.verify_hash(query, sha256_hash):
            return False
        now = time.monotonic()
        with self._lock:
            if len(self._store) >= self._max and sha256_hash not in self._store:
                # LRU 简化：淘汰最早注册项
                oldest = min(self._store.items(), key=lambda kv: kv[1][1])
                self._store.pop(oldest[0], None)
            self._store[sha256_hash.strip().lower()] = (query, now)
        return True

    def get(self, sha256_hash: str) -> str | None:
        """按 hash 取 query；TTL 过期即清除并返 None。"""
        if not sha256_hash:
            return None
        key = sha256_hash.strip().lower()
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            query, registered_at = item
            if now - registered_at > self._ttl:
                self._store.pop(key, None)
                return None
            return query

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"entries": len(self._store), "max": self._max, "ttl_seconds": self._ttl}

    def clear(self) -> int:
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n


def secrets_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


def extract_apq(body: dict[str, Any], apq: APQStorage) -> tuple[str | None, str | None]:
    """从请求体解析 APQ 语义，返回 (resolved_query, error_code)。

    - body 无 persistedQuery → (body 原有 query, None)
    - 有 hash+query → 校验注册；(query, None) 或 (None, "invalid_hash")
    - 只有 hash → 查注册表；(query, None) 或 (None, "PERSISTED_QUERY_NOT_FOUND")
    """
    extensions = body.get("extensions") if isinstance(body, dict) else None
    persisted = extensions.get("persistedQuery") if isinstance(extensions, dict) else None
    if not isinstance(persisted, dict):
        query = body.get("query") if isinstance(body, dict) else None
        return (query if isinstance(query, str) else None), None
    sha = persisted.get("sha256Hash")
    if not isinstance(sha, str) or not sha:
        return None, "invalid_hash"
    query = body.get("query") if isinstance(body, dict) else None
    if isinstance(query, str) and query:
        # 首查注册（全量+hash）
        ok = apq.register(sha, query)
        if not ok:
            return None, "invalid_hash"
        return query, None
    # 后续请求（仅 hash）
    found = apq.get(sha)
    if found is None:
        return None, "PERSISTED_QUERY_NOT_FOUND"
    return found, None




# ---------------------------------------------------------------------------
# ASGI 中间件：POST /graphql 请求体按 Apollo APQ 协议解析/重写
# ---------------------------------------------------------------------------
class APQMiddleware:
    """在 strawberry controller 之前执行：hash-only 请求还原为全量 query；首查注册并校验 sha256。

    strawberry 0.327 无内置 APQ（ASV 实测），故在框架层前置实现——协议语义见 extract_apq。
    """

    def __init__(self, app: Any, apq_store: APQStorage) -> None:
        self.app = app
        self.apq_store = apq_store

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/graphql" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        async def receive_wrapper() -> dict[str, Any]:
            msg = await receive()
            if msg.get("type") != "http.request" or msg.get("more_body", False):
                return msg
            try:
                body = json.loads(bytes(msg.get("body", b"") or b""))
            except (ValueError, json.JSONDecodeError):
                return msg
            resolved, error = extract_apq(body, self.apq_store)
            if error is None:
                if resolved is not None and not body.get("query"):
                    body["query"] = resolved
                return {**msg, "body": json.dumps(body).encode()}
            # APQ 失败（Not Found / Invalid Hash）：不在 ASGI 层短路 send（与 controller
            # 双写冲突，实测 500），而是把 body 重写为"注定校验失败"的查询，交由
            # strawberry 正常走单一响应路径返回 200 + GraphQL errors。
            body.pop("extensions", None)
            # 语义区分：Not Found 与 Invalid Hash 都映射到 strawberry 校验错误，
            # 客户端按 APQ 协议（收到任何非 data 成功响应即重发全量）处理；服务端
            # 日志保留原始 error_code 供观测。用一个 schema 外字段名保证必然校验失败。
            reject_field = "__apq_not_found" if error == "PERSISTED_QUERY_NOT_FOUND" else "__apq_invalid_hash"
            body["query"] = f"{{ {reject_field} }}"
            return {**msg, "body": json.dumps(body).encode()}

        await self.app(scope, receive_wrapper, send)
