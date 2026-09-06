from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterprise_ekb.config import load_config


@dataclass
class SeedResult:
    store: str
    target: int
    inserted: int
    seconds: float
    status: str
    note: str = ""

    @property
    def qps(self) -> float:
        if self.seconds <= 0:
            return 0.0
        return self.inserted / self.seconds


def _run_with_retry(operation: Any, max_retries: int, base_delay_seconds: float) -> Any:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            time.sleep(base_delay_seconds * (2**attempt))
    if last_error is None:
        raise RuntimeError("retry failed without captured error")
    raise last_error


def _batched_range(total: int, batch_size: int):
    start = 0
    while start < total:
        end = min(total, start + batch_size)
        yield start, end
        start = end


def _seed_tidb(total: int, batch_size: int, max_retries: int, base_delay_seconds: float) -> SeedResult:
    try:
        import pymysql
    except Exception as exc:
        return SeedResult("tidb", total, 0, 0.0, "skipped", f"pymysql unavailable: {exc}")

    cfg = load_config()
    started = time.perf_counter()
    inserted = 0
    conn = pymysql.connect(
        host=cfg.tidb_host,
        port=cfg.tidb_port,
        user=cfg.tidb_user,
        password=cfg.tidb_password,
        database=cfg.tidb_database,
        autocommit=False,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS synthetic_perf_records (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    tenant_id VARCHAR(64) NOT NULL,
                    region_id VARCHAR(32) NOT NULL,
                    record_key VARCHAR(64) NOT NULL,
                    payload_json JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_record_key (record_key),
                    KEY idx_tenant_region (tenant_id, region_id)
                )
                """
            )

            for begin, end in _batched_range(total, batch_size):
                rows: list[tuple[str, str, str, str]] = []
                for i in range(begin, end):
                    tenant = f"tenant-{i % 5000:04d}"
                    region = ["cn-north-1", "eu-west-1", "ap-southeast-1", "us-east-1"][i % 4]
                    record_key = f"seed-{i:010d}"
                    payload = json.dumps({"idx": i, "kind": "synthetic", "ts": int(time.time())})
                    rows.append((tenant, region, record_key, payload))
                _run_with_retry(
                    lambda: cur.executemany(
                        """
                        INSERT INTO synthetic_perf_records (tenant_id, region_id, record_key, payload_json)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE payload_json = VALUES(payload_json)
                        """,
                        rows,
                    ),
                    max_retries=max_retries,
                    base_delay_seconds=base_delay_seconds,
                )
                _run_with_retry(
                    conn.commit,
                    max_retries=max_retries,
                    base_delay_seconds=base_delay_seconds,
                )
                inserted += len(rows)
    except Exception as exc:
        conn.rollback()
        elapsed = time.perf_counter() - started
        return SeedResult("tidb", total, inserted, elapsed, "failed", str(exc))
    finally:
        conn.close()

    elapsed = time.perf_counter() - started
    return SeedResult("tidb", total, inserted, elapsed, "ok")


def _seed_redis(total: int, batch_size: int, max_retries: int, base_delay_seconds: float) -> SeedResult:
    try:
        import redis
    except Exception as exc:
        return SeedResult("redis", total, 0, 0.0, "skipped", f"redis unavailable: {exc}")

    cfg = load_config()
    started = time.perf_counter()
    inserted = 0
    client = redis.Redis.from_url(
        cfg.redis_url,
        max_connections=cfg.redis_max_connections,
        socket_timeout=cfg.redis_socket_timeout_seconds,
        socket_connect_timeout=cfg.redis_socket_connect_timeout_seconds,
        decode_responses=False,
    )

    try:
        for begin, end in _batched_range(total, batch_size):
            pipe = client.pipeline(transaction=False)
            for i in range(begin, end):
                key = f"ekb:seed:redis:{i:010d}"
                value = json.dumps({"idx": i, "tenant": i % 5000, "region": i % 4}, separators=(",", ":"))
                pipe.set(key, value)
            _run_with_retry(
                pipe.execute,
                max_retries=max_retries,
                base_delay_seconds=base_delay_seconds,
            )
            inserted += end - begin
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return SeedResult("redis", total, inserted, elapsed, "failed", str(exc))

    elapsed = time.perf_counter() - started
    return SeedResult("redis", total, inserted, elapsed, "ok")


def _seed_neo4j(total: int, batch_size: int, max_retries: int, base_delay_seconds: float) -> SeedResult:
    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        return SeedResult("neo4j", total, 0, 0.0, "skipped", f"neo4j unavailable: {exc}")

    cfg = load_config()
    started = time.perf_counter()
    inserted = 0
    driver = GraphDatabase.driver(
        cfg.neo4j_uri,
        auth=(cfg.neo4j_username, cfg.neo4j_password),
        max_connection_pool_size=cfg.neo4j_max_connection_pool_size,
    )

    query = (
        "UNWIND $rows AS row "
        "MERGE (n:PerfEntity {id: row.id}) "
        "SET n.tenant_id = row.tenant_id, n.region_id = row.region_id, n.updated_at = timestamp()"
    )
    try:
        with driver.session() as session:
            session.run(
                "CREATE CONSTRAINT perf_entity_id_unique IF NOT EXISTS FOR (n:PerfEntity) REQUIRE n.id IS UNIQUE"
            ).consume()
            for begin, end in _batched_range(total, batch_size):
                rows = []
                for i in range(begin, end):
                    rows.append(
                        {
                            "id": f"perf-{i:010d}",
                            "tenant_id": f"tenant-{i % 5000:04d}",
                            "region_id": ["cn", "eu", "apac", "us"][i % 4],
                        }
                    )
                _run_with_retry(
                    lambda: session.run(query, rows=rows).consume(),
                    max_retries=max_retries,
                    base_delay_seconds=base_delay_seconds,
                )
                inserted += len(rows)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return SeedResult("neo4j", total, inserted, elapsed, "failed", str(exc))
    finally:
        driver.close()

    elapsed = time.perf_counter() - started
    return SeedResult("neo4j", total, inserted, elapsed, "ok")


def _seed_milvus(total: int, batch_size: int, dimension: int, max_retries: int, base_delay_seconds: float) -> SeedResult:
    try:
        from pymilvus import DataType, MilvusClient
    except Exception as exc:
        return SeedResult("milvus", total, 0, 0.0, "skipped", f"pymilvus unavailable: {exc}")

    cfg = load_config()
    milvus_uri = cfg.milvus_uri
    if milvus_uri in {"http://127.0.0.1:19530", "http://localhost:19530"}:
        milvus_uri = "./tmp/milvus_lite.db"
    started = time.perf_counter()
    inserted = 0
    client = MilvusClient(uri=milvus_uri, token=cfg.milvus_token, db_name=cfg.milvus_db_name)
    collection_name = "ekb_perf_vectors"

    try:
        if not client.has_collection(collection_name):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field("id", DataType.INT64, is_primary=True)
            schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
            schema.add_field("region_id", DataType.VARCHAR, max_length=32)
            schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dimension)
            index_params = client.prepare_index_params()
            index_params.add_index(field_name="vector", index_type="IVF_FLAT", metric_type="COSINE", params={"nlist": 1024})
            client.create_collection(collection_name=collection_name, schema=schema, index_params=index_params)

        for begin, end in _batched_range(total, batch_size):
            rows: list[dict[str, Any]] = []
            for i in range(begin, end):
                vector = [float((i + j) % 100) / 100.0 for j in range(dimension)]
                rows.append(
                    {
                        "id": i + 1,
                        "tenant_id": f"tenant-{i % 5000:04d}",
                        "region_id": ["cn", "eu", "apac", "us"][i % 4],
                        "vector": vector,
                    }
                )
            _run_with_retry(
                lambda: client.upsert(collection_name=collection_name, data=rows),
                max_retries=max_retries,
                base_delay_seconds=base_delay_seconds,
            )
            inserted += len(rows)
    except Exception as exc:
        elapsed = time.perf_counter() - started
        return SeedResult("milvus", total, inserted, elapsed, "failed", str(exc))

    elapsed = time.perf_counter() - started
    return SeedResult("milvus", total, inserted, elapsed, "ok")


def _write_summary(path: Path, results: list[SeedResult]) -> None:
    payload = {
        "generated_at": int(time.time()),
        "stores": [
            {
                "store": r.store,
                "target": r.target,
                "inserted": r.inserted,
                "seconds": round(r.seconds, 3),
                "qps": round(r.qps, 2),
                "status": r.status,
                "note": r.note,
            }
            for r in results
        ],
        "all_ok": all(r.status == "ok" for r in results if r.status != "skipped"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed 1M+ synthetic records across EKB data stores")
    parser.add_argument("--records-per-store", type=int, default=1_000_000)
    parser.add_argument("--batch-size", type=int, default=5_000)
    parser.add_argument("--milvus-dim", type=int, default=8)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base-delay-seconds", type=float, default=0.2)
    parser.add_argument(
        "--stores",
        type=str,
        default="tidb,redis,neo4j,milvus",
        help="comma-separated: tidb,redis,neo4j,milvus",
    )
    parser.add_argument(
        "--summary-path",
        type=str,
        default="perf/reports/seed-latest-summary.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stores = {item.strip().lower() for item in args.stores.split(",") if item.strip()}

    runners: list[tuple[str, Any]] = []
    if "tidb" in stores:
        runners.append(
            (
                "tidb",
                lambda: _seed_tidb(
                    args.records_per_store,
                    args.batch_size,
                    args.max_retries,
                    args.retry_base_delay_seconds,
                ),
            )
        )
    if "redis" in stores:
        runners.append(
            (
                "redis",
                lambda: _seed_redis(
                    args.records_per_store,
                    args.batch_size,
                    args.max_retries,
                    args.retry_base_delay_seconds,
                ),
            )
        )
    if "neo4j" in stores:
        runners.append(
            (
                "neo4j",
                lambda: _seed_neo4j(
                    args.records_per_store,
                    max(1_000, min(args.batch_size, 10_000)),
                    args.max_retries,
                    args.retry_base_delay_seconds,
                ),
            )
        )
    if "milvus" in stores:
        runners.append(
            (
                "milvus",
                lambda: _seed_milvus(
                    args.records_per_store,
                    max(500, min(args.batch_size, 2_000)),
                    args.milvus_dim,
                    args.max_retries,
                    args.retry_base_delay_seconds,
                ),
            )
        )

    if not runners:
        print("[seed] no valid stores selected")
        return 1

    results: list[SeedResult] = []
    for name, runner in runners:
        print(f"[seed] start {name} target={args.records_per_store}")
        result: SeedResult = runner()
        print(
            f"[seed] {name} status={result.status} inserted={result.inserted}/{result.target} "
            f"seconds={result.seconds:.2f} qps={result.qps:.2f} note={result.note}"
        )
        results.append(result)

    summary_path = Path(args.summary_path)
    _write_summary(summary_path, results)
    print(f"[seed] summary written: {summary_path}")

    failed = [r for r in results if r.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
