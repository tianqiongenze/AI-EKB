"""CockroachDB control-plane store (PG wire), following the reference ESP
platform's ADR-24 data-plane decision: CRDB as primary datastore.

Dialect conversion from the TiDB (MySQL) lineage SQL:
- placeholder ? -> %s is handled by inheriting the TiDB method bodies only
  where they already use %s; this store overrides SQL with ? placeholders by
  re-implementing against psycopg (%s) where needed.
- AUTO_INCREMENT -> GENERATED ALWAYS AS IDENTITY
- TINYINT(1) -> SMALLINT / BOOLEAN
- JSON -> JSONB, KEY idx -> CREATE INDEX, backticks dropped
- ON UPDATE CURRENT_TIMESTAMP -> explicit updated_at writes

Follower reads (review §10 read-write separation, real data plane): read
methods run `AS OF SYSTEM TIME follower_read_timestamp()` inside read-only
transactions, serving from the closest replica — the ESP-proven pattern.
Single-region (LAN 3-node Raft) keeps writes at consensus latency.

Read staleness is bounded by CRDB's follower_read_timestamp() (~4.8s);
callers relying on read-your-write must use the primary-path methods.
"""

from __future__ import annotations

import contextlib
import json
import threading
import uuid
from typing import Any

from enterprise_ekb.schemas import (
    BusinessCapabilityManifest,
    BusinessDomain,
    CapabilityMaturity,
    ConnectorAdapterType,
    ConnectorAuthType,
    ConnectorEnvelope,
    ConnectorProfile,
    ConnectorProfileStatus,
    ConnectorRunStatus,
    ConnectorSystem,
    SkillManifest,
    SkillStage,
    SubAgentTaskRecord,
    SubAgentTaskStatus,
)
from enterprise_ekb.storage import SkillRow, SQLiteControlPlaneStore

try:
    import psycopg2
    import psycopg2.extensions
    import psycopg2.extras
except ImportError:
    psycopg2 = None


class _ThreadLocalPgConnection:
    def __init__(self, connect_kwargs: dict[str, Any]) -> None:
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for CockroachDB mode")
        self._connect_kwargs = connect_kwargs
        self._local = threading.local()

    def _connect(self) -> Any:
        assert psycopg2 is not None
        return psycopg2.connect(**self._connect_kwargs)

    def _current(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = self._connect()
            self._local.conn = conn
            return conn
        return conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current(), name)



def _ensure_json(value: Any) -> Any:
    """psycopg2 parses JSONB to Python objects; tolerate both dict/list and str."""
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    return json.loads(value)




def _write_op(fn):
    """Commit-or-rollback wrapper for CRDB write methods.

    Without the rollback, a failed statement leaves an aborted transaction
    open on the thread-local connection — under the CCL free-tier open-txn
    cap this wedges the whole cluster (found by the C-2 write load test)."""

    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:
            self._rollback()
            raise

    return wrapper




def _row_jsonable(value: Any) -> Any:
    """Normalize CRDB rows (dict/list/scalar) for JSON caching/serialization.

    psycopg2 returns datetime/Decimal objects; the cache layer json.dumps and
    HTTP encoders need primitives (audit-query 500 regression, 2026-09-20)."""
    from datetime import date as _date
    from datetime import datetime as _dt
    from decimal import Decimal as _Decimal

    if isinstance(value, dict):
        return {k: _row_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_row_jsonable(v) for v in value]
    if isinstance(value, _dt):
        return value.isoformat()
    if isinstance(value, _date):
        return value.isoformat()
    if isinstance(value, _Decimal):
        return float(value)
    return value


class CockroachDBControlPlaneStore(SQLiteControlPlaneStore):
    """Primary datastore on CRDB (PG wire). Inherits row<->model mapping logic
    shape from the SQLite store but re-implements all SQL for PG dialect."""

    READ_METHODS = frozenset({
        "list_skills",
        "get_sub_agent_task",
        "list_sub_agent_tasks_by_supervisor",
        "recent_audits",
        "recent_outbox_events",
        "list_business_capabilities",
    })

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        follower_reads: bool = True,
    ) -> None:
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for CockroachDB mode")
        connect_kwargs: dict[str, Any] = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "dbname": database,
            "connect_timeout": 10,
            "sslmode": "disable",
        }
        self._conn = _ThreadLocalPgConnection(connect_kwargs)
        self._follower_reads = follower_reads
        self._instance_id = f"crdb-{uuid.uuid4().hex[:12]}"
        self._run_migrations()
        self._migrate_seed_skills()

    # ------------------------------------------------------------------
    # connection helpers
    # ------------------------------------------------------------------

    def _cursor(self) -> Any:
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def _read_commit(self) -> None:
        """Close the implicit txn a plain read opened (psycopg2 keeps txns open
        after SELECT; CRDB free-tier counts every open txn against the cap)."""
        self._commit()

    def _commit(self) -> None:
        self._conn.commit()

    def _rollback(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.rollback()

    def _follower_clause(self) -> str:
        """Deprecated: statement-level AS OF breaks on txn reuse (CRDB v24.3).
        Kept for documentation; follower reads use _read_only_txn exclusively."""
        return " AS OF SYSTEM TIME follower_read_timestamp()" if self._follower_reads else ""

    def _read_only_txn(self, statements: list[tuple[str, tuple[Any, ...]]]) -> list[dict[str, Any]]:
        """Run read statements in one follower-read read-only transaction."""
        conn = self._conn._current()
        out: list[dict[str, Any]] = []
        try:
            # A prior plain read on this thread-local conn may have left the txn
            # open (psycopg2 opens txns on SELECT); SET TRANSACTION must be the
            # first statement, so close any dangling txn first.
            if conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
                conn.rollback()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # psycopg2 opens the txn implicitly at the first statement; SET
                # TRANSACTION must be that first statement (CRDB requirement,
                # verified against the live 3-node cluster: v24.3.11).
                cur.execute("SET TRANSACTION AS OF SYSTEM TIME follower_read_timestamp(), READ ONLY")
                for sql, params in statements:
                    cur.execute(sql, params)
                    if cur.description is not None:
                        out.extend(dict(r) for r in cur.fetchall())
            conn.commit()
        except Exception:
            self._rollback()
            raise
        return out

    # ------------------------------------------------------------------
    # migrations (PG dialect)
    # ------------------------------------------------------------------

    def _run_migrations(self) -> None:
        ddl = [
            # core tables
            """
            CREATE TABLE IF NOT EXISTS skills (
                skill_name VARCHAR(191) NOT NULL,
                version VARCHAR(64) NOT NULL,
                owner VARCHAR(191) NOT NULL,
                risk_level VARCHAR(32) NOT NULL,
                stage VARCHAR(32) NOT NULL,
                allowed_tools_json JSONB NOT NULL,
                allowed_domains_json JSONB NOT NULL,
                residency_scope_json JSONB NOT NULL,
                input_schema_json JSONB NOT NULL,
                output_schema_json JSONB NOT NULL,
                changelog TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (skill_name, version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audits (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id VARCHAR(191) NOT NULL,
                region_id VARCHAR(64) NOT NULL,
                plant_id VARCHAR(128) NOT NULL,
                user_or_agent_id VARCHAR(191) NOT NULL,
                skill_name VARCHAR(191) NOT NULL,
                skill_version VARCHAR(64) NOT NULL,
                tool_name VARCHAR(191) NOT NULL,
                decision_reason VARCHAR(128) NOT NULL,
                accepted SMALLINT NOT NULL,
                payload_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audits_tenant_created ON audits (tenant_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS harness_runs (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tenant_id VARCHAR(191) NOT NULL,
                skill_name VARCHAR(191) NOT NULL,
                skill_version VARCHAR(64) NOT NULL,
                quality_score DECIMAL NOT NULL,
                security_score DECIMAL NOT NULL,
                regression_score DECIMAL NOT NULL,
                latency_p95_ms INT NOT NULL,
                verdict VARCHAR(32) NOT NULL,
                payload_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                event_type VARCHAR(191) NOT NULL,
                payload_json JSONB NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                retries INT NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                published_at TIMESTAMPTZ NULL,
                claimed_by VARCHAR(128) NOT NULL DEFAULT '',
                claimed_at TIMESTAMPTZ NULL,
                next_retry_at TIMESTAMPTZ NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_outbox_claimed ON outbox_events (status, claimed_by, claimed_at)",
            "CREATE INDEX IF NOT EXISTS idx_outbox_retry ON outbox_events (status, next_retry_at, id)",
            """
            CREATE TABLE IF NOT EXISTS business_capabilities (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                domain VARCHAR(64) NOT NULL,
                capability_type VARCHAR(128) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                owner VARCHAR(191) NOT NULL,
                maturity VARCHAR(32) NOT NULL,
                tags_json JSONB NOT NULL,
                metadata_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (domain, capability_type, title)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_domain_maturity ON business_capabilities (domain, maturity)",
            """
            CREATE TABLE IF NOT EXISTS connector_envelopes (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                connector_system VARCHAR(64) NOT NULL,
                direction VARCHAR(32) NOT NULL,
                tenant_id VARCHAR(191) NOT NULL,
                region_id VARCHAR(64) NOT NULL,
                source_id VARCHAR(191) NOT NULL,
                event_type VARCHAR(191) NOT NULL,
                occurred_at VARCHAR(64) NOT NULL,
                idempotency_key VARCHAR(191) NOT NULL,
                payload_json JSONB NOT NULL,
                metadata_json JSONB NOT NULL,
                status VARCHAR(32) NOT NULL,
                replay_count INT NOT NULL DEFAULT 0,
                last_replayed_at TIMESTAMPTZ NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (connector_system, idempotency_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_connector_system_created ON connector_envelopes (connector_system, created_at)",
            """
            CREATE TABLE IF NOT EXISTS connector_profiles (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                connector_system VARCHAR(64) NOT NULL,
                profile_name VARCHAR(191) NOT NULL,
                base_url VARCHAR(1024) NOT NULL,
                auth_type VARCHAR(64) NOT NULL,
                auth_config_json JSONB NOT NULL,
                timeout_ms INT NOT NULL,
                pull_batch_size INT NOT NULL,
                status VARCHAR(32) NOT NULL,
                metadata_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (connector_system, profile_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS connector_checkpoints (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                connector_system VARCHAR(64) NOT NULL,
                profile_name VARCHAR(191) NOT NULL,
                cursor VARCHAR(1024) NOT NULL,
                watermark VARCHAR(128),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (connector_system, profile_name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS connector_pull_runs (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                connector_system VARCHAR(64) NOT NULL,
                profile_name VARCHAR(191) NOT NULL,
                mode VARCHAR(32) NOT NULL,
                from_cursor VARCHAR(1024),
                next_cursor VARCHAR(1024) NOT NULL,
                pulled_count INT NOT NULL,
                accepted_count INT NOT NULL,
                replayed_count INT NOT NULL,
                sample_event_ids_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sub_agent_tasks (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                task_id VARCHAR(191) NOT NULL,
                idempotency_key VARCHAR(191) NOT NULL,
                tenant_id VARCHAR(191) NOT NULL,
                region_id VARCHAR(128) NOT NULL,
                plant_id VARCHAR(191),
                supervisor_id VARCHAR(191) NOT NULL,
                sub_agent_type VARCHAR(191) NOT NULL,
                task_objective TEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                attempt_count INT NOT NULL DEFAULT 0,
                result_payload_json JSONB NOT NULL,
                error TEXT,
                worker_id VARCHAR(191),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ NULL,
                UNIQUE (task_id),
                UNIQUE (tenant_id, idempotency_key)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sub_agent_supervisor_created ON sub_agent_tasks (supervisor_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_sub_agent_status_updated ON sub_agent_tasks (status, updated_at)",
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            # P0-② document pipeline + P0-④ RBAC (PG dialect)
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id VARCHAR(191) NOT NULL PRIMARY KEY,
                tenant_id VARCHAR(191) NOT NULL,
                source_name VARCHAR(512) NOT NULL,
                source_type VARCHAR(32) NOT NULL,
                mime_type VARCHAR(191) NOT NULL,
                content_sha256 VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                page_count INT NOT NULL DEFAULT 0,
                chunk_count INT NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                metadata_json JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_documents_tenant_created ON documents (tenant_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id VARCHAR(64) NOT NULL,
                doc_id VARCHAR(191) NOT NULL,
                seq INT NOT NULL,
                chunk_type VARCHAR(16) NOT NULL,
                parent_id VARCHAR(64) NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                tokens INT NOT NULL DEFAULT 0,
                metadata_json JSONB NOT NULL DEFAULT '{}'::JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (doc_id, chunk_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_seq ON document_chunks (doc_id, seq)",
            "CREATE INDEX IF NOT EXISTS idx_document_chunks_type ON document_chunks (chunk_type)",
            """
            CREATE TABLE IF NOT EXISTS rbac_users (
                user_id VARCHAR(191) NOT NULL PRIMARY KEY,
                role VARCHAR(16) NOT NULL,
                tenant_id VARCHAR(191) NOT NULL DEFAULT 'group',
                department VARCHAR(191) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
        ]
        conn = self._conn._current()
        with conn.cursor() as cur:
            for statement in ddl:
                cur.execute(statement)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT (version) DO NOTHING",
                ("0001_init_crdb",),
            )
        conn.commit()

    def _migrate_seed_skills(self) -> None:
        # parity with SQLite store behaviour: none seeded by default
        return None

    # ------------------------------------------------------------------
    # P0-② documents + P0-④ RBAC (PG dialect overrides)
    # ------------------------------------------------------------------
    @staticmethod
    def _document_row_to_dict(row: dict | None) -> dict | None:
        if row is None:
            return None
        doc = _row_jsonable(dict(row))
        raw_meta = doc.pop("metadata_json", None) or {}
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except (TypeError, ValueError):
                raw_meta = {}
        doc["metadata"] = raw_meta if isinstance(raw_meta, dict) else {}
        return doc

    @_write_op
    def upsert_document(self, doc: dict) -> None:
        if doc is None:
            raise ValueError("doc_required")
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    doc_id, tenant_id, source_name, source_type, mime_type,
                    content_sha256, status, page_count, chunk_count, error, metadata_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (doc_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    page_count = EXCLUDED.page_count,
                    chunk_count = EXCLUDED.chunk_count,
                    error = EXCLUDED.error,
                    metadata_json = EXCLUDED.metadata_json,
                    updated_at = now()
                """,
                (
                    doc.get("doc_id", ""),
                    doc.get("tenant_id", "group"),
                    doc.get("source_name", "")[:512],
                    doc.get("source_type", ""),
                    doc.get("mime_type", ""),
                    doc.get("content_sha256", ""),
                    doc.get("status", "parsed"),
                    int(doc.get("page_count", 0) or 0),
                    int(doc.get("chunk_count", 0) or 0),
                    str(doc.get("error", "") or ""),
                    json.dumps(doc.get("metadata", {}), ensure_ascii=False),
                ),
            )
        self._commit()

    def get_document(self, doc_id: str) -> dict | None:
        if not doc_id:
            return None
        rows = self._read_only_txn(
            [("SELECT * FROM documents WHERE doc_id = %s", (doc_id,))]
        )
        return self._document_row_to_dict(rows[0] if rows else None)

    def list_documents(self, tenant_id: str | None = None, limit: int = 50) -> list[dict]:
        effective_limit = max(1, min(int(limit or 50), 200))
        if tenant_id:
            rows = self._read_only_txn(
                [
                    (
                        "SELECT * FROM documents WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
                        (tenant_id, effective_limit),
                    )
                ]
            )
        else:
            rows = self._read_only_txn(
                [("SELECT * FROM documents ORDER BY created_at DESC LIMIT %s", (effective_limit,))]
            )
        out: list[dict] = []
        for row in rows:
            mapped = self._document_row_to_dict(row)
            if mapped is not None:
                out.append(mapped)
        return out

    @_write_op
    def replace_document_chunks(self, doc_id: str, chunks: list[dict]) -> None:
        if not doc_id:
            raise ValueError("doc_id_required")
        if chunks is None:
            chunks = []
        with self._cursor() as cur:
            cur.execute("DELETE FROM document_chunks WHERE doc_id = %s", (doc_id,))
            for chunk in chunks:
                raw_meta = chunk.get("metadata_json", "{}") or "{}"
                if isinstance(raw_meta, dict):
                    raw_meta = json.dumps(raw_meta, ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, doc_id, seq, chunk_type, parent_id,
                        content, tokens, metadata_json
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        chunk.get("chunk_id", ""),
                        doc_id,
                        int(chunk.get("seq", 0) or 0),
                        chunk.get("chunk_type", "text"),
                        chunk.get("parent_id", "") or "",
                        chunk.get("content", ""),
                        int(chunk.get("tokens", 0) or 0),
                        raw_meta,
                    ),
                )
        self._commit()

    def list_document_chunks(
        self, doc_id: str, chunk_type: str | None = None, limit: int = 200
    ) -> list[dict]:
        if not doc_id:
            return []
        effective_limit = max(1, min(int(limit or 200), 1000))
        if chunk_type:
            rows = self._read_only_txn(
                [
                    (
                        """
                        SELECT chunk_id, doc_id, seq, chunk_type, parent_id, content, tokens, metadata_json
                        FROM document_chunks WHERE doc_id = %s AND chunk_type = %s
                        ORDER BY seq LIMIT %s
                        """,
                        (doc_id, chunk_type, effective_limit),
                    )
                ]
            )
        else:
            rows = self._read_only_txn(
                [
                    (
                        """
                        SELECT chunk_id, doc_id, seq, chunk_type, parent_id, content, tokens, metadata_json
                        FROM document_chunks WHERE doc_id = %s
                        ORDER BY seq LIMIT %s
                        """,
                        (doc_id, effective_limit),
                    )
                ]
            )
        out: list[dict] = []
        for row in rows or []:
            item = _row_jsonable(dict(row))
            raw_meta = item.pop("metadata_json", None) or {}
            if isinstance(raw_meta, str):
                try:
                    raw_meta = json.loads(raw_meta)
                except (TypeError, ValueError):
                    raw_meta = {}
            item["metadata"] = raw_meta if isinstance(raw_meta, dict) else {}
            out.append(item)
        return out

    @_write_op
    def upsert_user(
        self, user_id: str, role: str, tenant_id: str = "group", department: str = ""
    ) -> None:
        if not user_id or not role:
            raise ValueError("user_id_and_role_required")
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO rbac_users (user_id, role, tenant_id, department)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET
                    role = EXCLUDED.role,
                    tenant_id = EXCLUDED.tenant_id,
                    department = EXCLUDED.department,
                    updated_at = now()
                """,
                (user_id, role, tenant_id or "group", department or ""),
            )
        self._commit()

    def get_user_role(self, user_id: str) -> str | None:
        if not user_id:
            return None
        rows = self._read_only_txn(
            [("SELECT role FROM rbac_users WHERE user_id = %s", (user_id,))]
        )
        return rows[0]["role"] if rows else None

    def list_users(self) -> list[dict]:
        rows = self._read_only_txn(
            [
                (
                    """
                    SELECT user_id, role, tenant_id, department, created_at, updated_at
                    FROM rbac_users ORDER BY user_id
                    """,
                    (),
                )
            ]
        )
        return [_row_jsonable(dict(row)) for row in rows or []]

    @_write_op
    def delete_user(self, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id_required")
        with self._cursor() as cur:
            cur.execute("DELETE FROM rbac_users WHERE user_id = %s", (user_id,))
        self._commit()

    # ------------------------------------------------------------------
    # skills
    # ------------------------------------------------------------------

    def list_skills(self) -> list[SkillRow]:
        sql = "SELECT * FROM skills ORDER BY skill_name, version"
        with self._cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        self._read_commit()
        result: list[SkillRow] = []
        for row in rows:
            result.append(
                SkillRow(
                    manifest=SkillManifest(
                        skill_name=row["skill_name"],
                        version=row["version"],
                        owner=row["owner"],
                        risk_level=row["risk_level"],
                        allowed_tools=_ensure_json(row["allowed_tools_json"]),
                        allowed_domains=_ensure_json(row["allowed_domains_json"]),
                        residency_scope=_ensure_json(row["residency_scope_json"]),
                        input_schema=_ensure_json(row["input_schema_json"]),
                        output_schema=_ensure_json(row["output_schema_json"]),
                        changelog=row["changelog"],
                    ),
                    stage=row["stage"],
                )
            )
        return result

    @_write_op
    def create_skill(self, manifest: SkillManifest, stage: SkillStage) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO skills (skill_name, version, owner, risk_level, stage,
                    allowed_tools_json, allowed_domains_json, residency_scope_json,
                    input_schema_json, output_schema_json, changelog)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    manifest.skill_name,
                    manifest.version,
                    manifest.owner,
                    manifest.risk_level.value,
                    stage.value,
                    json.dumps(manifest.allowed_tools),
                    json.dumps(manifest.allowed_domains),
                    json.dumps(manifest.residency_scope),
                    json.dumps(manifest.input_schema),
                    json.dumps(manifest.output_schema),
                    manifest.changelog,
                ),
            )
        self._commit()

    @_write_op
    def update_skill_stage(self, skill_name: str, version: str, stage: SkillStage) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE skills SET stage = %s, updated_at = now() WHERE skill_name = %s AND version = %s",
                (stage.value, skill_name, version),
            )
        self._commit()

    # ------------------------------------------------------------------
    # audits
    # ------------------------------------------------------------------

    def append_audit(
        self,
        tenant_id: str,
        region_id: str,
        plant_id: str,
        user_or_agent_id: str,
        skill_name: str,
        skill_version: str,
        tool_name: str,
        decision_reason: str,
        accepted: bool,
        payload: dict[str, Any],
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO audits (tenant_id, region_id, plant_id, user_or_agent_id,
                    skill_name, skill_version, tool_name, decision_reason, accepted, payload_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    tenant_id,
                    region_id,
                    plant_id,
                    user_or_agent_id,
                    skill_name,
                    skill_version,
                    tool_name,
                    decision_reason,
                    1 if accepted else 0,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        self._commit()

    def recent_audits(self, limit: int) -> list[dict[str, Any]]:
        statements = [(
            "SELECT * FROM audits ORDER BY id DESC LIMIT %s",
            (limit,),
        )]
        raw = self._read_only_txn(statements)
        rows: list[dict[str, Any]] = []
        for row in raw:
            item = {k: _row_jsonable(v) for k, v in row.items()}
            item["payload_json"] = _ensure_json(item.get("payload_json"))
            item["accepted"] = bool(item.get("accepted"))
            rows.append(item)
        return rows

    # ------------------------------------------------------------------
    # outbox
    # ------------------------------------------------------------------

    @_write_op
    def enqueue_outbox(self, event_type: str, payload: dict[str, Any]) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO outbox_events (event_type, payload_json) VALUES (%s, %s) RETURNING id",
                (event_type, json.dumps(payload, ensure_ascii=False)),
            )
            event_id = int(cur.fetchone()["id"])
        self._commit()
        return event_id

    @_write_op
    def claim_pending_outbox(self, limit: int, claim_timeout_seconds: int = 30) -> list[dict[str, Any]]:
        def _operation() -> list[dict[str, Any]]:
            self._conn._current().autocommit = False
            conn = self._conn._current()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    UPDATE outbox_events SET status='pending', claimed_by='', claimed_at=NULL
                    WHERE status='processing' AND next_retry_at IS NOT NULL AND next_retry_at <= now()
                    """
                )
                cur.execute(
                    """
                    UPDATE outbox_events
                    SET status='processing', claimed_by=%s, claimed_at=now(),
                        next_retry_at = now() + (%s || ' seconds')::interval
                    WHERE id IN (
                        SELECT id FROM outbox_events
                        WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at <= now())
                        ORDER BY id LIMIT %s
                    ) AND status='pending'
                    """,
                    (self._instance_id, str(claim_timeout_seconds), limit),
                )
                cur.execute(
                    "SELECT id, event_type, payload_json, retries FROM outbox_events WHERE status='processing' AND claimed_by=%s ORDER BY id LIMIT %s",
                    (self._instance_id, limit),
                )
                rows = cur.fetchall()
            conn.commit()
            return [
                {
                    "id": int(r["id"]),
                    "event_type": r["event_type"],
                    "payload": _ensure_json(r["payload_json"]),
                    "retries": int(r["retries"]),
                }
                for r in rows
            ]

        return _operation()

    @_write_op
    def mark_outbox_published(self, event_id: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE outbox_events SET status='published', claimed_by='', claimed_at=NULL, published_at=now() WHERE id=%s",
                (event_id,),
            )
        self._commit()

    @_write_op
    def mark_outbox_failed(self, event_id: int, error: str) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE outbox_events
                SET retries = retries + 1, last_error=%s, claimed_by='', claimed_at=NULL,
                    next_retry_at = CASE WHEN retries + 1 >= 10 THEN NULL
                                         ELSE now() + LEAST(300, POW(2, LEAST(8, retries + 1)) * 1000) * INTERVAL '1 millisecond' END,
                    status = CASE WHEN retries + 1 >= 10 THEN 'dead' ELSE 'pending' END
                WHERE id=%s
                """,
                (error[:500], event_id),
            )
        self._commit()

    def outbox_stats(self) -> dict[str, int]:
        with self._cursor() as cur:
            cur.execute("SELECT status, COUNT(*) AS count FROM outbox_events GROUP BY status")
            rows = cur.fetchall()
        self._read_commit()
        stats: dict[str, int] = {"pending": 0, "processing": 0, "published": 0, "dead": 0}
        for row in rows:
            stats[str(row["status"])] = int(row["count"])
        return stats

    def outbox_claim_instance_id(self) -> str:
        return self._instance_id

    def recent_outbox_events(self, limit: int) -> list[dict[str, Any]]:
        statements = [(
            "SELECT id, event_type, payload_json, status, created_at FROM outbox_events ORDER BY id DESC LIMIT %s",
            (limit,),
        )]
        rows = self._read_only_txn(statements)
        for row in rows:
            row = {k: _row_jsonable(v) for k, v in row.items()}
            row["payload_json"] = _ensure_json(row.get("payload_json"))
        return rows

    # ------------------------------------------------------------------
    # sub-agent tasks
    # ------------------------------------------------------------------

    def get_sub_agent_task(self, task_id: str) -> SubAgentTaskRecord | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM sub_agent_tasks WHERE task_id = %s",
                (task_id,),
            )
            row = cur.fetchone()
        self._read_commit()
        return self._sub_agent_row_to_record(row) if row else None

    def get_sub_agent_task_by_idempotency(self, tenant_id: str, idempotency_key: str) -> SubAgentTaskRecord | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM sub_agent_tasks WHERE tenant_id=%s AND idempotency_key=%s AND status='queued' ORDER BY id DESC LIMIT 1",
                (tenant_id, idempotency_key),
            )
            row = cur.fetchone()
        self._read_commit()
        return self._sub_agent_row_to_record(row) if row else None

    def create_sub_agent_task(
        self,
        task_id: str,
        idempotency_key: str,
        tenant_id: str,
        region_id: str,
        plant_id: str,
        supervisor_id: str,
        sub_agent_type: str,
        task_objective: str,
        status: SubAgentTaskStatus,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO sub_agent_tasks (task_id, idempotency_key, tenant_id, region_id, plant_id,
                    supervisor_id, sub_agent_type, task_objective, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (task_id, idempotency_key, tenant_id, region_id, plant_id, supervisor_id, sub_agent_type, task_objective, status.value),
            )
        self._commit()

    def list_sub_agent_tasks_by_supervisor(self, supervisor_id: str, limit: int) -> list[SubAgentTaskRecord]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM sub_agent_tasks WHERE supervisor_id=%s ORDER BY id DESC LIMIT %s",
                (supervisor_id, limit),
            )
            rows = cur.fetchall()
        self._read_commit()
        return [r for r in (self._sub_agent_row_to_record(row) for row in rows) if r is not None]

    def update_sub_agent_task_status(
        self,
        task_id: str,
        status: SubAgentTaskStatus,
        worker_id: str | None,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE sub_agent_tasks
                SET status=%s,
                    worker_id=COALESCE(%s, worker_id),
                    result_payload_json=COALESCE(%s::jsonb, result_payload_json),
                    error=COALESCE(%s, error),
                    attempt_count = attempt_count + %s,
                    updated_at=now(),
                    completed_at = CASE WHEN %s IN ('completed','failed','dlq') THEN now() ELSE completed_at END
                WHERE task_id=%s
                """,
                (
                    status.value,
                    worker_id,
                    json.dumps(result_payload) if result_payload is not None else None,
                    error,
                    1 if increment_attempt else 0,
                    status.value,
                    task_id,
                ),
            )
        self._commit()

    def _sub_agent_row_to_record(self, row: dict[str, Any]) -> SubAgentTaskRecord:
        payload = _ensure_json(row.get("result_payload_json"))
        return SubAgentTaskRecord(
            task_id=row["task_id"],
            idempotency_key=row["idempotency_key"],
            tenant_id=row["tenant_id"],
            region_id=row["region_id"],
            plant_id=row["plant_id"] or "",
            supervisor_id=row["supervisor_id"],
            sub_agent_type=row["sub_agent_type"],
            task_objective=row["task_objective"],
            status=SubAgentTaskStatus(row["status"]),
            attempt_count=int(row["attempt_count"]),
            result_payload=payload or {},
            error=row.get("error"),
            worker_id=row.get("worker_id"),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=str(row["completed_at"]) if row.get("completed_at") else None,
        )

    # ------------------------------------------------------------------
    # business capabilities
    # ------------------------------------------------------------------

    @_write_op
    def upsert_business_capability(self, capability: BusinessCapabilityManifest) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO business_capabilities (domain, capability_type, title, description, owner, maturity, tags_json, metadata_json, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (domain, capability_type, title) DO UPDATE
                SET description=EXCLUDED.description, owner=EXCLUDED.owner, maturity=EXCLUDED.maturity,
                    tags_json=EXCLUDED.tags_json, metadata_json=EXCLUDED.metadata_json, updated_at=now()
                RETURNING id
                """,
                (
                    capability.domain.value,
                    capability.capability_type,
                    capability.title,
                    capability.description,
                    capability.owner,
                    capability.maturity.value,
                    json.dumps(capability.tags, ensure_ascii=False),
                    json.dumps(capability.metadata, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        self._commit()
        return int(row["id"])

    def list_business_capabilities(
        self,
        domain: BusinessDomain | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[BusinessCapabilityManifest]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain is not None:
            clauses.append("domain = %s")
            params.append(domain.value)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(title LIKE %s ESCAPE '\\' OR description LIKE %s ESCAPE '\\' OR capability_type LIKE %s ESCAPE '\\')"
            )
            like = f"%{escaped}%"
            params.extend([like, like, like])
        sql = "SELECT * FROM business_capabilities"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY domain, capability_type, title LIMIT %s"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        self._read_commit()
        result: list[BusinessCapabilityManifest] = []
        for row in rows:
            result.append(
                BusinessCapabilityManifest(
                    domain=BusinessDomain(row["domain"]),
                    capability_type=row["capability_type"],
                    title=row["title"],
                    description=row["description"],
                    owner=row["owner"],
                    maturity=CapabilityMaturity(row["maturity"]),
                    tags=_ensure_json(row["tags_json"]),
                    metadata=_ensure_json(row["metadata_json"]),
                )
            )
        return result

    # ------------------------------------------------------------------
    # connectors
    # ------------------------------------------------------------------

    @_write_op
    def persist_connector_envelope(self, envelope: ConnectorEnvelope) -> tuple[int, bool]:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_envelopes (connector_system, direction, tenant_id, region_id,
                    source_id, event_type, occurred_at, idempotency_key, payload_json, metadata_json, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'accepted')
                ON CONFLICT (connector_system, idempotency_key) DO UPDATE SET updated_at=now()
                RETURNING id, (xmax = 0) AS inserted
                """,
                (
                    envelope.connector_system.value,
                    envelope.direction.value,
                    envelope.tenant_id,
                    envelope.region_id,
                    envelope.source_id,
                    envelope.event_type,
                    envelope.occurred_at,
                    envelope.idempotency_key,
                    json.dumps(envelope.payload, ensure_ascii=False),
                    json.dumps(envelope.metadata, ensure_ascii=False),
                ),
            )
            row = cur.fetchone()
        self._commit()
        return int(row["id"]), bool(row["inserted"])

    @_write_op
    def update_connector_status(self, row_id: int, status: ConnectorRunStatus) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE connector_envelopes SET status=%s, updated_at=now() WHERE id=%s",
                (status.value, row_id),
            )
        self._commit()

    def list_connector_envelopes(
        self,
        connector_system: ConnectorSystem | None = None,
        status: ConnectorRunStatus | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if connector_system is not None:
            clauses.append("connector_system = %s")
            params.append(connector_system.value)
        if status is not None:
            clauses.append("status = %s")
            params.append(status.value)
        sql = "SELECT * FROM connector_envelopes"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        self._read_commit()
        out: list[dict[str, Any]] = []
        for row in rows:
            row = dict(row)
            for key in ("payload_json", "metadata_json"):
                row[key] = _ensure_json(row.get(key))
            row = {k: _row_jsonable(v) for k, v in row.items()}
            out.append(row)
        return out

    # ------------------------------------------------------------------
    # profiles / checkpoints / pull runs
    # ------------------------------------------------------------------

    @_write_op
    def upsert_connector_profile(self, profile: ConnectorProfile) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_profiles (connector_system, profile_name, base_url, auth_type,
                    auth_config_json, timeout_ms, pull_batch_size, status, metadata_json, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (connector_system, profile_name) DO UPDATE
                SET base_url=EXCLUDED.base_url, auth_type=EXCLUDED.auth_type,
                    auth_config_json=EXCLUDED.auth_config_json, timeout_ms=EXCLUDED.timeout_ms,
                    pull_batch_size=EXCLUDED.pull_batch_size, status=EXCLUDED.status,
                    metadata_json=EXCLUDED.metadata_json, updated_at=now()
                """,
                (
                    profile.connector_system.value,
                    profile.profile_name,
                    profile.base_url,
                    profile.auth_type.value,
                    json.dumps(profile.auth_config),
                    profile.timeout_ms,
                    profile.pull_batch_size,
                    profile.status.value,
                    json.dumps(profile.metadata, ensure_ascii=False),
                ),
            )
        self._commit()

    def list_connector_profiles(self, connector_system: ConnectorSystem | None = None) -> list[ConnectorProfile]:
        sql = "SELECT * FROM connector_profiles"
        params: tuple[Any, ...] = ()
        if connector_system is not None:
            sql += " WHERE connector_system = %s"
            params = (connector_system.value,)
        sql += " ORDER BY profile_name"
        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        self._read_commit()
        profiles: list[ConnectorProfile] = []
        for row in rows:
            profiles.append(
                ConnectorProfile(
                    connector_system=ConnectorSystem(row["connector_system"]),
                    profile_name=row["profile_name"],
                    base_url=row["base_url"],
                    auth_type=ConnectorAuthType(row["auth_type"]),
                    auth_config=_ensure_json(row["auth_config_json"]),
                    timeout_ms=int(row["timeout_ms"]),
                    pull_batch_size=int(row["pull_batch_size"]),
                    status=ConnectorProfileStatus(row["status"]),
                    metadata=_ensure_json(row["metadata_json"]),
                    adapter_type=ConnectorAdapterType("generic"),
                )
            )
        return profiles

    def get_connector_checkpoint(self, connector_system: ConnectorSystem, profile_name: str) -> dict[str, Any] | None:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM connector_checkpoints WHERE connector_system=%s AND profile_name=%s",
                (connector_system.value, profile_name),
            )
            row = cur.fetchone()
        self._read_commit()
        return dict(row) if row else None

    def update_connector_checkpoint(
        self,
        connector_system: ConnectorSystem,
        profile_name: str,
        cursor: str,
        watermark: str | None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_checkpoints (connector_system, profile_name, cursor, watermark, updated_at)
                VALUES (%s,%s,%s,%s,now())
                ON CONFLICT (connector_system, profile_name) DO UPDATE
                SET cursor=EXCLUDED.cursor, watermark=EXCLUDED.watermark, updated_at=now()
                """,
                (connector_system.value, profile_name, cursor, watermark),
            )
        self._commit()

    def append_connector_pull_run(
        self,
        connector_system: ConnectorSystem,
        profile_name: str,
        mode: str,
        from_cursor: str | None,
        next_cursor: str,
        pulled_count: int,
        accepted_count: int,
        replayed_count: int,
        sample_event_ids: list[int],
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_pull_runs (connector_system, profile_name, mode, from_cursor,
                    next_cursor, pulled_count, accepted_count, replayed_count, sample_event_ids_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    connector_system.value,
                    profile_name,
                    mode,
                    from_cursor,
                    next_cursor,
                    pulled_count,
                    accepted_count,
                    replayed_count,
                    json.dumps(sample_event_ids),
                ),
            )
        self._commit()

    def list_connector_pull_runs(self, connector_system: ConnectorSystem, profile_name: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM connector_pull_runs WHERE connector_system=%s AND profile_name=%s ORDER BY id DESC LIMIT %s",
                (connector_system.value, profile_name, limit),
            )
            rows = cur.fetchall()
        self._read_commit()
        out: list[dict[str, Any]] = []
        for row in rows:
            row = dict(row)
            row["sample_event_ids_json"] = _ensure_json(row.get("sample_event_ids_json"))
            out.append(row)
        return out

    @_write_op
    def append_harness_run(self, payload: dict[str, Any]) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO harness_runs (tenant_id, skill_name, skill_version, quality_score,
                    security_score, regression_score, latency_p95_ms, verdict, payload_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    payload["tenant_id"],
                    payload["skill_name"],
                    payload["skill_version"],
                    payload["quality_score"],
                    payload["security_score"],
                    payload["regression_score"],
                    payload["latency_p95_ms"],
                    payload["verdict"],
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        self._commit()
