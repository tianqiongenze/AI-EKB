"""1 亿条测试数据生成器 + warmup（P1 阶段：压测数据面）。

数据分布（总 100,000,000 行，全部走 CRDB COPY 批量通道，实测最快路径）：
- audits              60,000,000（审计主链路，压测 /audit/query 与 /industrial/*）
- document_chunks    20,000,000（含 200,000 documents，压测 /documents/* 与 GraphQL chunks）
- connector_envelopes 15,000,000（压测连接器幂等重放）
- outbox_events        5,000,000（published 态，压测 readyz/outbox 统计）
- rbac_users           100,000（RBAC 绑定规模）
Redis 预热：随机 10,000 个热点 audit 查询键写入 L2。

warmup 功能：
- `--warmup` 模式：不灌数，只对 CRDB 各表做全表统计刷新（ANALYZE）+ 热点查询预跑 N 轮，
  让 RocksDB/PEEPERS 计划缓存与 block cache 就位，压测前消除冷启动偏差。

运行位置：必须在集群内（kubectl exec pod）执行——容器内直连 CRDB，绕过 NodePort。
进度落盘：stdout 每批一行（wc 可 grep）。

用法（集群内）：
  python -m scripts.seed_1e8 --mode generate --batches all
  python -m scripts.seed_1e8 --mode warmup --rounds 50
  python -m scripts.seed_1e8 --mode verify
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

import psycopg2

CRDB = dict(
    host="cockroachdb.infra.svc.cluster.local",
    port=26257,
    user="root",
    password="",
    dbname="ekb_control_plane",
)

random.seed(20260921)

SKILLS = ["llm-demo", "smoke-skill", "ui-skill-22590", "doc-qa", "graph-explore"]
TOOLS = ["ask", "search", "ingest", "report"]
REASONS = ["ok", "policy_denied", "residency_violation", "tool_not_allowed", "skill_not_found"]
TENANTS = ["group", "yadea-wuxi", "yadea-tianjin", "partner-a"]
REGIONS = ["cn-north-1", "cn-east-1"]
CHUNK_TYPES = ["text", "table", "image", "parent"]
DOC_NAMES = ["工艺手册", "质检标准", "装配指南", "电池规格", "车架工艺", "售后手册"]

TOTAL = {
    "audits": 60_000_000,
    "documents": 200_000,
    "document_chunks": 20_000_000,
    "connector_envelopes": 15_000_000,
    "outbox_events": 5_000_000,
    "rbac_users": 100_000,
}
BATCH = 50_000  # 每批行数（COPY 单批；20000→50000 实测提升单连接吞吐）


def _connect():
    return psycopg2.connect(**CRDB)


def _rand_ts(base: datetime, spread_hours: int = 24 * 30) -> str:
    return (base - timedelta(seconds=random.randint(0, spread_hours * 3600))).isoformat()


def gen_audit_rows(n: int, start_id: int, base_ts: datetime) -> str:
    """TSV 行：tenant, region, plant, user, skill, ver, tool, reason, accepted, payload, ts
    （id 为 GENERATED ALWAYS IDENTITY，COPY 不带）"""
    lines = []
    for i in range(n):
        tenant = random.choice(TENANTS)
        skill = random.choice(SKILLS)
        tool = random.choice(TOOLS)
        reason = random.choices(REASONS, weights=[88, 4, 2, 3, 3])[0]
        accepted = 1 if reason == "ok" else 0
        latency = random.randint(8, 900)
        payload = json.dumps(
            {"message_id": f"m{start_id + i}", "latency_ms": latency, "q_len": random.randint(5, 400)},
            ensure_ascii=False,
        )
        ts = _rand_ts(base_ts)
        lines.append(
            f"{tenant}\t{random.choice(REGIONS)}\tp{random.randint(1, 20)}\t"
            f"u{random.randint(1, 500000)}\t{skill}\t1.0.0\t{tool}\t{reason}\t{accepted}\t{payload}\t{ts}"
        )
    return "\n".join(lines) + "\n"


def gen_chunk_rows(n: int, start_seq: int, doc_id_start: int, base_ts: datetime) -> str:
    lines = []
    for i in range(n):
        seq = start_seq + i
        doc_id = f"doc{doc_id_start + i // 100:07d}"  # 每 doc 100 chunks
        ctype = random.choices(CHUNK_TYPES, weights=[70, 15, 5, 10])[0]
        content = (
            f"工艺段落 {seq}：TTFAR 电池产线工序参数与质检标准说明。"
            f"涵盖涂布、辊压、装配、化成等关键步骤。row-{seq}。"
        )
        tokens = max(8, len(content) // 2)
        lines.append(
            f"chk{seq:012d}\t{doc_id}\t{i % 100}\t{ctype}\t{doc_id}-parent\t{content}\t{tokens}\t{{}}\t{_rand_ts(base_ts)}"
        )
    return "\n".join(lines) + "\n"


def gen_connector_rows(n: int, start_id: int, base_ts: datetime) -> str:
    """id 为 identity，COPY 不带。列: system,direction,tenant,region,source,event,occurred,idem,payload,meta,status,replay,created"""
    lines = []
    for i in range(n):
        eid = start_id + i
        lines.append(
            f"erp\tinbound\tgroup\tcn-north-1\tsrc{eid % 100000}\tstock.moved\t"
            f"ts{eid}\tik{eid:012d}\t{{\"qty\":{random.randint(1,500)}}}\t{{}}\taccepted\t0\t{ _rand_ts(base_ts)}"
        )
    return "\n".join(lines) + "\n"


def gen_outbox_rows(n: int, start_id: int, base_ts: datetime) -> str:
    # 列序: event_type,payload_json,status,retries,last_error,created_at,published_at（id 为 identity 不带）
    lines = []
    for i in range(n):
        eid = start_id + i
        ts = _rand_ts(base_ts)
        lines.append(f"benchmark.event\t{{\"i\":{eid}}}\tpublished\t1\t\t{ts}\t{ts}")
    return "\n".join(lines) + "\n"


def _copy(cur, table: str, columns: str, tsv: str) -> None:
    import io

    cur.copy_expert(f"COPY {table} ({columns}) FROM STDIN", io.StringIO(tsv))


def generate(table: str, conn) -> None:
    cur = conn.cursor()
    if table == "audits":
        cols = "tenant_id, region_id, plant_id, user_or_agent_id, skill_name, skill_version, tool_name, decision_reason, accepted, payload_json, created_at"
        base_ts = datetime.now(timezone.utc)
        t0 = time.time()
        for batch_i in range(TOTAL["audits"] // BATCH):
            start_id = batch_i * BATCH
            _copy(cur, "audits", cols, gen_audit_rows(BATCH, start_id, base_ts))
            conn.commit()
            if batch_i % 50 == 0:
                done = (batch_i + 1) * BATCH
                rate = done / max(time.time() - t0, 0.1)
                print(f"[audits] {done}/{TOTAL['audits']} rows, {rate:.0f} rows/s", flush=True)
    elif table == "document_chunks":
        # 先补 documents 维表
        cur.execute("SELECT coalesce(max(id),0) FROM documents")
        docs_have = cur.fetchone()[0]
        need_docs = TOTAL["documents"]
        if docs_have < need_docs:
            dcols = "doc_id, tenant_id, source_name, source_type, mime_type, content_sha256, status, page_count, chunk_count, error, metadata_json"
            for batch_i in range((need_docs - docs_have + BATCH - 1) // BATCH):
                n = min(BATCH, need_docs - docs_have - batch_i * BATCH)
                rows = []
                for j in range(n):
                    did = f"doc{docs_have + batch_i * BATCH + j:07d}"
                    rows.append(
                        f"{did}\tgroup\t{random.choice(DOC_NAMES)}.md\tmd\ttext/markdown\thash{did}\tindexed\t{random.randint(1,80)}\t100\t{{}}\t\"\""
                    )
                _copy(cur, "documents", dcols, "\n".join(rows) + "\n")
                conn.commit()
            print(f"[documents] seeded to {need_docs}", flush=True)
        cur.execute("SELECT coalesce(count(*),0) FROM document_chunks")
        have = cur.fetchone()[0]
        cols = "chunk_id, doc_id, seq, chunk_type, parent_id, content, tokens, metadata_json, created_at"
        base_ts = datetime.now(timezone.utc)
        t0 = time.time()
        for batch_i in range((TOTAL["document_chunks"] - have) // BATCH):
            _copy(cur, "document_chunks", cols, gen_chunk_rows(BATCH, have + batch_i * BATCH, 0, base_ts))
            conn.commit()
            if batch_i % 50 == 0:
                done = (batch_i + 1) * BATCH
                print(f"[document_chunks] {done}/{TOTAL['document_chunks'] - have} new rows, {done / max(time.time() - t0, 0.1):.0f} rows/s", flush=True)
    elif table == "connector_envelopes":
        cur.execute("SELECT coalesce(max(id),0) FROM connector_envelopes")
        existing = cur.fetchone()[0]
        cols = "connector_system, direction, tenant_id, region_id, source_id, event_type, occurred_at, idempotency_key, payload_json, metadata_json, status, replay_count, created_at"  # noqa: E501（13 列子集）
        base_ts = datetime.now(timezone.utc)
        t0 = time.time()
        for batch_i in range(TOTAL["connector_envelopes"] // BATCH):
            _copy(cur, "connector_envelopes", cols, gen_connector_rows(BATCH, batch_i * BATCH, base_ts))
            conn.commit()
            if batch_i % 50 == 0:
                done = (batch_i + 1) * BATCH
                print(f"[connector_envelopes] {done}/{TOTAL['connector_envelopes']} rows, {done / max(time.time() - t0, 0.1):.0f} rows/s", flush=True)
    elif table == "outbox_events":
        cols = "event_type, payload_json, status, retries, last_error, created_at, published_at"
        base_ts = datetime.now(timezone.utc)
        t0 = time.time()
        for batch_i in range(TOTAL["outbox_events"] // BATCH):
            _copy(cur, "outbox_events", cols, gen_outbox_rows(BATCH, batch_i * BATCH, base_ts))
            conn.commit()
            if batch_i % 50 == 0:
                done = (batch_i + 1) * BATCH
                print(f"[outbox_events] {done}/{TOTAL['outbox_events']} rows, {done / max(time.time() - t0, 0.1):.0f} rows/s", flush=True)
    elif table == "rbac_users":
        cur.execute("SELECT coalesce(count(*),0) FROM rbac_users")
        have = cur.fetchone()[0]
        roles = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3"]
        cols = "user_id, role, tenant_id, department"
        remaining = TOTAL["rbac_users"] - have
        if remaining <= 0:
            print(f"[rbac_users] already {have}, skip", flush=True)
        else:
            rows = []
            for i in range(remaining):
                rows.append(f"user{have + i:07d}\t{random.choice(roles)}\t{random.choice(TENANTS)}\tdept{i % 50}")
            _copy(cur, "rbac_users", cols, "\n".join(rows) + "\n")
            conn.commit()
            print(f"[rbac_users] seeded {len(rows)}", flush=True)
    cur.close()


def warmup(rounds: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    print("[warmup] ANALYZE all bench tables...", flush=True)
    for t in ("audits", "document_chunks", "connector_envelopes", "outbox_events", "rbac_users"):
        try:
            cur.execute(f"ANALYZE {t}")
            conn.commit()
            print(f"  analyzed {t}", flush=True)
        except Exception as exc:
            conn.rollback()
            print(f"  analyze {t} skipped: {type(exc).__name__}", flush=True)
    print(f"[warmup] {rounds} rounds of hot-path queries...", flush=True)
    queries = [
        ("SELECT count(*) FROM audits WHERE tenant_id=%s AND created_at > now() - interval '1 hour'", ("group",)),
        ("SELECT skill_name, count(*) FROM audits WHERE accepted=1 GROUP BY skill_name", ()),
        ("SELECT * FROM document_chunks WHERE doc_id=%s ORDER BY seq LIMIT 100", ("doc0000000",)),
        ("SELECT count(*) FROM connector_envelopes WHERE status='accepted'", ()),
        ("SELECT decision_reason, count(*) FROM audits GROUP BY decision_reason", ()),
    ]
    for r in range(rounds):
        for qi, (q, params) in enumerate(queries):
            t0 = time.time()
            cur.execute(q, params)
            cur.fetchall()
            conn.commit()
            if r == rounds - 1:
                print(f"  q{qi} last-round {1000 * (time.time() - t0):.1f}ms", flush=True)
    cur.close()
    conn.close()
    print("[warmup] done", flush=True)


def verify() -> None:
    conn = _connect()
    cur = conn.cursor()
    total = 0
    for t in ("audits", "documents", "document_chunks", "connector_envelopes", "outbox_events", "rbac_users"):
        cur.execute(f"SELECT count(*) FROM {t}")
        n = cur.fetchone()[0]
        total += n
        print(f"{t}: {n:,}", flush=True)
    conn.commit()
    cur.close()
    conn.close()
    print(f"TOTAL: {total:,} (target 100,000,000)", flush=True)


def generate_audits_shard(shard: int, shards: int) -> None:
    """audits 分片并行灌：shard i 处理 [i::shards] 批区间，各自连接提交。"""
    conn = _connect()
    cur = conn.cursor()
    cols = "tenant_id, region_id, plant_id, user_or_agent_id, skill_name, skill_version, tool_name, decision_reason, accepted, payload_json, created_at"
    base_ts = datetime.now(timezone.utc)
    total_batches = TOTAL["audits"] // BATCH
    t0 = time.time()
    done = 0
    for batch_i in range(shard, total_batches, shards):
        start_id = batch_i * BATCH
        _copy(cur, "audits", cols, gen_audit_rows(BATCH, start_id, base_ts))
        conn.commit()
        done += BATCH
        if (batch_i // shards) % 20 == 0:
            rate = done / max(time.time() - t0, 0.1)
            print(f"[audits-shard{shard}/{shards}] {done}/{total_batches * BATCH} rows, {rate:.0f} rows/s", flush=True)
    cur.close()
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["generate", "warmup", "verify"], required=True)
    ap.add_argument("--table", default=None, help="generate 单表名；缺省全表顺序灌")
    ap.add_argument("--rounds", type=int, default=50, help="warmup 轮数")
    ap.add_argument("--audits-parallel", type=int, default=1, help="audits 分片并行度")
    args = ap.parse_args()
    if args.mode == "verify":
        verify()
    elif args.mode == "warmup":
        warmup(args.rounds)
    else:
        if args.table == "audits" and args.audits_parallel > 1:
            # CCL 铁律：fork 继承 psycopg2 连接句柄会泄漏开放事务（mp fork 模式已实证把集群打到上限）。
            # 改 subprocess：主进程零连接，每个分片独立 python 进程（SHARD 模式），天然隔离。
            import os
            import subprocess as sp

            procs = []
            for i in range(args.audits_parallel):
                env = dict(os.environ, SEED_SHARD=str(i), SEED_SHARDS=str(args.audits_parallel))
                procs.append(sp.Popen([sys.executable, __file__, "--mode", "generate", "--table", "audits-shard"], env=env))
            for pr in procs:
                pr.wait()
            print("=== audits parallel generate complete ===", flush=True)
        elif args.table == "audits-shard":
            shard, shards = int(os.environ["SEED_SHARD"]), int(os.environ["SEED_SHARDS"])
            generate_audits_shard(shard, shards)
        else:
            conn = _connect()
            tables = [args.table] if args.table else ["rbac_users", "audits", "document_chunks", "connector_envelopes", "outbox_events"]
            for t in tables:
                print(f"=== generating {t} ===", flush=True)
                generate(t, conn)
            conn.close()
            print("=== generate complete ===", flush=True)
