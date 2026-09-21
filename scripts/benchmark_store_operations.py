from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from enterprise_ekb.config import load_config


@dataclass
class BenchmarkResult:
    store: str
    operation: str
    samples: int
    ok: int
    failed: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    avg_ms: float
    qps: float
    note: str = ""


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * ratio)
    return ordered[idx]


def _summarize(store: str, operation: str, latencies_ms: list[float], failed: int, total_seconds: float, note: str = "") -> BenchmarkResult:
    ok = len(latencies_ms)
    samples = ok + failed
    avg = statistics.fmean(latencies_ms) if latencies_ms else 0.0
    return BenchmarkResult(
        store=store,
        operation=operation,
        samples=samples,
        ok=ok,
        failed=failed,
        p50_ms=_percentile(latencies_ms, 0.50),
        p95_ms=_percentile(latencies_ms, 0.95),
        p99_ms=_percentile(latencies_ms, 0.99),
        avg_ms=avg,
        qps=(ok / total_seconds) if total_seconds > 0 else 0.0,
        note=note,
    )


def _bench_tidb(samples: int) -> BenchmarkResult:
    try:
        import pymysql
    except Exception as exc:
        return BenchmarkResult("tidb", "select_by_key", samples, 0, samples, 0, 0, 0, 0, 0, f"pymysql unavailable: {exc}")

    cfg = load_config()
    conn = pymysql.connect(
        host=cfg.tidb_host,
        port=cfg.tidb_port,
        user=cfg.tidb_user,
        password=cfg.tidb_password,
        database=cfg.tidb_database,
        autocommit=True,
        charset="utf8mb4",
    )
    latencies: list[float] = []
    failed = 0
    started = time.perf_counter()
    try:
        with conn.cursor() as cur:
            for _ in range(samples):
                idx = random.randint(0, 999_999)
                key = f"seed-{idx:010d}"
                t0 = time.perf_counter()
                try:
                    cur.execute(
                        "SELECT id, tenant_id, region_id FROM synthetic_perf_records WHERE record_key = %s LIMIT 1",
                        (key,),
                    )
                    cur.fetchone()
                    latencies.append((time.perf_counter() - t0) * 1000)
                except Exception:
                    failed += 1
    finally:
        conn.close()
    return _summarize("tidb", "select_by_key", latencies, failed, time.perf_counter() - started)


def _bench_redis(samples: int) -> BenchmarkResult:
    try:
        import redis
    except Exception as exc:
        return BenchmarkResult("redis", "get", samples, 0, samples, 0, 0, 0, 0, 0, f"redis unavailable: {exc}")

    cfg = load_config()
    client = redis.Redis.from_url(
        cfg.redis_url,
        max_connections=cfg.redis_max_connections,
        socket_timeout=cfg.redis_socket_timeout_seconds,
        socket_connect_timeout=cfg.redis_socket_connect_timeout_seconds,
        decode_responses=False,
    )
    latencies: list[float] = []
    failed = 0
    started = time.perf_counter()
    for _ in range(samples):
        idx = random.randint(0, 999_999)
        key = f"ekb:seed:redis:{idx:010d}"
        t0 = time.perf_counter()
        try:
            client.get(key)
            latencies.append((time.perf_counter() - t0) * 1000)
        except Exception:
            failed += 1
    return _summarize("redis", "get", latencies, failed, time.perf_counter() - started)


def _bench_neo4j(samples: int) -> BenchmarkResult:
    try:
        from neo4j import GraphDatabase
    except Exception as exc:
        return BenchmarkResult("neo4j", "match_by_id", samples, 0, samples, 0, 0, 0, 0, 0, f"neo4j unavailable: {exc}")

    cfg = load_config()
    driver = GraphDatabase.driver(
        cfg.neo4j_uri,
        auth=(cfg.neo4j_username, cfg.neo4j_password),
        max_connection_pool_size=cfg.neo4j_max_connection_pool_size,
    )
    latencies: list[float] = []
    failed = 0
    started = time.perf_counter()
    try:
        with driver.session() as session:
            for _ in range(samples):
                idx = random.randint(0, 999_999)
                node_id = f"perf-{idx:010d}"
                t0 = time.perf_counter()
                try:
                    session.run("MATCH (n:PerfEntity {id: $id}) RETURN n.id LIMIT 1", id=node_id).single()
                    latencies.append((time.perf_counter() - t0) * 1000)
                except Exception:
                    failed += 1
    finally:
        driver.close()
    return _summarize("neo4j", "match_by_id", latencies, failed, time.perf_counter() - started)


def _bench_milvus(samples: int, dimension: int) -> BenchmarkResult:
    try:
        from pymilvus import MilvusClient
    except Exception as exc:
        return BenchmarkResult("milvus", "vector_search", samples, 0, samples, 0, 0, 0, 0, 0, f"pymilvus unavailable: {exc}")

    cfg = load_config()
    milvus_uri = cfg.milvus_uri
    if milvus_uri in {"http://127.0.0.1:19530", "http://localhost:19530"}:
        milvus_uri = "./tmp/milvus_lite.db"
    client = MilvusClient(uri=milvus_uri, token=cfg.milvus_token, db_name=cfg.milvus_db_name)
    latencies: list[float] = []
    failed = 0
    started = time.perf_counter()
    query_vector = [0.01 * ((i % 10) + 1) for i in range(dimension)]

    for _ in range(samples):
        t0 = time.perf_counter()
        try:
            client.search(
                collection_name="ekb_perf_vectors",
                data=[query_vector],
                limit=10,
                search_params={"metric_type": "COSINE", "params": {"nprobe": 16}},
            )
            latencies.append((time.perf_counter() - t0) * 1000)
        except Exception:
            failed += 1

    return _summarize("milvus", "vector_search", latencies, failed, time.perf_counter() - started)


def _write_summary(path: Path, results: list[BenchmarkResult]) -> None:
    payload = {
        "generated_at": int(time.time()),
        "results": [
            {
                "store": r.store,
                "operation": r.operation,
                "samples": r.samples,
                "ok": r.ok,
                "failed": r.failed,
                "p50_ms": round(r.p50_ms, 3),
                "p95_ms": round(r.p95_ms, 3),
                "p99_ms": round(r.p99_ms, 3),
                "avg_ms": round(r.avg_ms, 3),
                "qps": round(r.qps, 3),
                "note": r.note,
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark datastore/cache operations against seeded data")
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--milvus-dim", type=int, default=8)
    parser.add_argument("--stores", type=str, default="tidb,redis,neo4j,milvus")
    parser.add_argument("--summary-path", type=str, default="perf/reports/store-benchmark-latest.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stores = {s.strip().lower() for s in args.stores.split(",") if s.strip()}
    results: list[BenchmarkResult] = []

    if "tidb" in stores:
        results.append(_bench_tidb(args.samples))
    if "redis" in stores:
        results.append(_bench_redis(args.samples))
    if "neo4j" in stores:
        results.append(_bench_neo4j(args.samples))
    if "milvus" in stores:
        results.append(_bench_milvus(args.samples, args.milvus_dim))

    if not results:
        print("[bench] no valid stores selected")
        return 1

    for r in results:
        print(
            f"[bench] {r.store}:{r.operation} ok={r.ok} failed={r.failed} "
            f"p95={r.p95_ms:.2f}ms p99={r.p99_ms:.2f}ms qps={r.qps:.2f} note={r.note}"
        )

    summary_path = Path(args.summary_path)
    _write_summary(summary_path, results)
    print(f"[bench] summary written: {summary_path}")

    failed = [r for r in results if r.failed > 0 and r.ok == 0]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
