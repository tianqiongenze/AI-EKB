from __future__ import annotations

import hashlib
import hmac
import importlib
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedisConfig:
    url: str
    max_connections: int = 200
    socket_timeout_seconds: float = 0.2
    socket_connect_timeout_seconds: float = 0.2


@dataclass(frozen=True)
class PulsarConfig:
    service_url: str
    token: str = ""
    tls_enabled: bool = False
    ca_cert_path: str = ""


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str
    max_connection_pool_size: int = 100


@dataclass(frozen=True)
class MilvusConfig:
    uri: str
    token: str = ""
    db_name: str = "default"


@dataclass(frozen=True)
class HttpRetryConfig:
    max_attempts: int = 3
    backoff_base_seconds: float = 0.2
    backoff_max_seconds: float = 2.0


class HttpAdapter:
    def __init__(self, timeout_ms: int, retry: HttpRetryConfig | None = None) -> None:
        self._timeout_ms = timeout_ms
        self._retry = retry or HttpRetryConfig()
        httpx_module = importlib.import_module("httpx")
        self._client = httpx_module.Client(timeout=timeout_ms / 1000, follow_redirects=False)

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        raise_for_status: bool = True,
    ) -> dict[str, Any]:
        attempt = 0
        last_exc: Exception | None = None
        importlib.import_module("httpx")
        while attempt < self._retry.max_attempts:
            attempt += 1
            try:
                response = self._client.get(url, headers=headers, params=params)
                if raise_for_status:
                    response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
                if attempt >= self._retry.max_attempts:
                    break
                time.sleep(min(self._retry.backoff_max_seconds, self._retry.backoff_base_seconds * attempt))
        if last_exc is None:
            raise RuntimeError("http_adapter_failed")
        raise last_exc

    def signed_get(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any],
        secret: str,
        signature_header: str = "X-Signature",
    ) -> dict[str, Any]:
        canonical = "&".join(f"{key}={params[key]}" for key in sorted(params.keys()))
        signature = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        signed_headers = dict(headers)
        signed_headers[signature_header] = signature
        return self.get(url=url, headers=signed_headers, params=params, raise_for_status=True)

    def close(self) -> None:
        self._client.close()


class HighPerformanceRedisClient:
    def __init__(self, config: RedisConfig) -> None:
        redis_module = importlib.import_module("redis")
        pool = redis_module.ConnectionPool.from_url(
            config.url,
            max_connections=config.max_connections,
            socket_timeout=config.socket_timeout_seconds,
            socket_connect_timeout=config.socket_connect_timeout_seconds,
            decode_responses=False,
            health_check_interval=15,
        )
        self._client = redis_module.Redis(connection_pool=pool)

    @property
    def client(self):
        return self._client

    def mget_json(self, keys: list[str]) -> list[dict[str, Any] | None]:
        values = self._client.mget(keys)
        result: list[dict[str, Any] | None] = []
        for value in values:
            if value is None:
                result.append(None)
            else:
                result.append(json.loads(value))
        return result

    def mset_json_with_ttl(self, items: dict[str, dict[str, Any]], ttl_seconds: int) -> None:
        pipe = self._client.pipeline(transaction=False)
        for key, value in items.items():
            pipe.setex(key, ttl_seconds, json.dumps(value, separators=(",", ":"), ensure_ascii=False))
        pipe.execute()


class HighPerformanceNeo4jClient:
    def __init__(self, config: Neo4jConfig) -> None:
        neo4j_module = importlib.import_module("neo4j")
        self._driver = neo4j_module.GraphDatabase.driver(
            config.uri,
            auth=(config.username, config.password),
            max_connection_pool_size=config.max_connection_pool_size,
        )

    def batch_upsert_relations(self, rows: list[dict[str, Any]]) -> None:
        query = (
            "UNWIND $rows AS row "
            "MERGE (a:Entity {id: row.source}) "
            "MERGE (b:Entity {id: row.target}) "
            "MERGE (a)-[r:RELATED {type: row.relation_type}]->(b)"
        )
        with self._driver.session() as session:
            session.run(query, rows=rows)

    def close(self) -> None:
        self._driver.close()


class HighPerformanceMilvusClient:
    def __init__(self, config: MilvusConfig) -> None:
        milvus_module = importlib.import_module("pymilvus")
        self._milvus = milvus_module
        self._client = milvus_module.MilvusClient(uri=config.uri, token=config.token, db_name=config.db_name)

    def batch_upsert(self, collection_name: str, rows: list[dict[str, Any]]) -> None:
        self._client.upsert(collection_name=collection_name, data=rows)

    def search(self, collection_name: str, vectors: list[list[float]], limit: int = 10) -> Any:
        return self._client.search(
            collection_name=collection_name,
            data=vectors,
            limit=limit,
            search_params={"metric_type": "COSINE", "params": {"ef": 128}},
        )


class HighPerformancePulsarClient:
    def __init__(self, config: PulsarConfig) -> None:
        pulsar_module = importlib.import_module("pulsar")
        auth = pulsar_module.AuthenticationToken(config.token) if config.token else None
        self._client = pulsar_module.Client(
            config.service_url,
            authentication=auth,
            tls_validate_hostname=config.tls_enabled,
            tls_trust_certs_file_path=config.ca_cert_path if config.ca_cert_path else None,
        )
        self._producers: dict[str, Any] = {}

    def publish_batch(self, topic: str, payloads: list[dict[str, Any]]) -> None:
        producer = self._get_or_create_producer(topic)
        for payload in payloads:
            producer.send(
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
                properties={"event_type": topic.split("/")[-1]},
            )

    def _get_or_create_producer(self, topic: str):
        pulsar_module = importlib.import_module("pulsar")
        if topic not in self._producers:
            self._producers[topic] = self._client.create_producer(
                topic,
                batching_enabled=True,
                batching_max_messages=1000,
                batching_max_publish_delay_ms=20,
                compression_type=pulsar_module.CompressionType.LZ4,
                send_timeout_millis=2000,
                block_if_queue_full=True,
            )
        return self._producers[topic]

    def close(self) -> None:
        for producer in self._producers.values():
            producer.flush()
        self._client.close()
