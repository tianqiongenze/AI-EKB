"""REST vs GraphQL 全链路压测对比（EKB 0.7 阶段）。

场景设计（同业务语义等价对比——公平性原则）：
  S1 列表页:  REST GET /documents?limit=20      ↔ GraphQL { documents(limit:20){...} }
  S2 详情+子资源: REST GET /documents/{id} + GET /documents/{id}/chunks（2 次往返）
              ↔ GraphQL 单请求 { document(docId){...} chunks(docId){...} }（1 次往返）
  S3 聚合面板: REST GET /industrial/kpis         ↔ GraphQL { kpiPanel{...} audits(limit:50){...} }

测量：每场景 N 请求串行 + 并发两档（1 / 8 并发），报告 p50/p95/p99/rps/err。
基线对（REST-before / GraphQL-after）自动落 docs/bench/ 下 JSON。

用法（集群内 pod 或任一可达 NodePort 的机器）：
  python scripts/bench_rest_vs_graphql.py --base http://10.167.2.175:30880 \
      --samples 200 --concurrency 1,8 --out docs/bench/bench-20260921.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone


def _get(base: str, path: str, timeout: float = 15.0) -> tuple[int, bytes]:
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return r.status, r.read()
    finally:
        pass


class Timer:
    def __init__(self) -> None:
        self.samples: list[float] = []
        self.errors = 0

    def run(self, fn) -> None:
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            self.errors += 1
        finally:
            self.samples.append((time.perf_counter() - t0) * 1000)

    def summary(self) -> dict:
        s = sorted(self.samples)
        n = len(s) or 1

        def pct(p: float) -> float:
            return s[min(n - 1, int(p * n))]

        return {
            "n": len(self.samples),
            "errors": self.errors,
            "p50_ms": round(pct(0.50), 1),
            "p95_ms": round(pct(0.95), 1),
            "p99_ms": round(pct(0.99), 1),
            "mean_ms": round(statistics.mean(s), 1) if s else 0,
            "rps": round(len(s) / (sum(s) / 1000), 1) if s else 0,
        }


def gql(base: str, query: str) -> bytes:
    req = urllib.request.Request(
        base + "/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def fetch_doc_id(base: str) -> str:
    _, body = _get(base, "/documents?limit=1")
    items = json.loads(body).get("items") or []
    if not items:
        raise SystemExit("no documents seeded; run documents ingest first")
    return items[0]["doc_id"]


def scenario_s1(base: str, samples: int, concurrency: int) -> dict:
    rest_t, gql_t = Timer(), Timer()

    def rest_call():
        _get(base, "/documents?limit=20")

    def gql_call():
        gql(base, "{ documents(limit: 20) { docId sourceName status pageCount chunkCount } }")

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(lambda _: rest_t.run(rest_call), range(samples)))
        list(ex.map(lambda _: gql_t.run(gql_call), range(samples)))
    return {"scenario": "S1_list", "concurrency": concurrency, "rest": rest_t.summary(), "graphql": gql_t.summary()}


def scenario_s2(base: str, samples: int, concurrency: int, doc_id: str) -> dict:
    rest_t, gql_t = Timer(), Timer()

    def rest_call():
        _get(base, f"/documents/{doc_id}")
        _get(base, f"/documents/{doc_id}/chunks?limit=20")

    def gql_call():
        q = ('{ document(docId: "%s") { sourceName status pageCount } '
             'chunks(docId: "%s", limit: 20) { seq chunkType tokens } }' % (doc_id, doc_id))
        gql(base, q)

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(lambda _: rest_t.run(rest_call), range(samples)))
        list(ex.map(lambda _: gql_t.run(gql_call), range(samples)))
    return {"scenario": "S2_detail_children", "concurrency": concurrency, "rest": rest_t.summary(), "graphql": gql_t.summary()}


def scenario_s3(base: str, samples: int, concurrency: int) -> dict:
    rest_t, gql_t = Timer(), Timer()

    def rest_call():
        _get(base, "/industrial/kpis")

    def gql_call():
        gql(base, "{ kpiPanel { records oee firstPassYield } audits(limit: 50) { tenantId accepted } }")

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(lambda _: rest_t.run(rest_call), range(samples)))
        list(ex.map(lambda _: gql_t.run(gql_call), range(samples)))
    return {"scenario": "S3_aggregate_panel", "concurrency": concurrency, "rest": rest_t.summary(), "graphql": gql_t.summary()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--concurrency", default="1,8")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    doc_id = fetch_doc_id(args.base)
    print(f"bench target={args.base} doc_id={doc_id} samples={args.samples}", flush=True)

    results = []
    for conc in [int(c) for c in args.concurrency.split(",")]:
        results.append(scenario_s1(args.base, args.samples, conc))
        print(f"S1 c={conc}: rest={results[-1]['rest']} gql={results[-1]['graphql']}", flush=True)
        results.append(scenario_s2(args.base, args.samples, conc, doc_id))
        print(f"S2 c={conc}: rest={results[-1]['rest']} gql={results[-1]['graphql']}", flush=True)
        results.append(scenario_s3(args.base, args.samples, conc))
        print(f"S3 c={conc}: rest={results[-1]['rest']} gql={results[-1]['graphql']}", flush=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": args.base,
        "samples_per_run": args.samples,
        "results": results,
    }
    out = args.out or f"docs/bench/bench-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    with open(out, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"saved → {out}", flush=True)


if __name__ == "__main__":
    main()
