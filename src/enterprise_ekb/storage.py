from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from enterprise_ekb.schemas import (
    BusinessCapabilityManifest,
    BusinessDomain,
    CapabilityMaturity,
    ConnectorAdapterType,
    ConnectorAuthType,
    ConnectorDirection,
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


@dataclass(frozen=True)
class SkillRow:
    manifest: SkillManifest
    stage: SkillStage


@dataclass(frozen=True)
class OutboxEvent:
    event_type: str
    payload: dict[str, Any]


_T = TypeVar("_T")


def _json_loads_or_empty(raw: Any) -> dict:
    """容错 JSON 解析：坏数据返回空 dict，不阻断读路径。"""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


class _ThreadLocalSQLiteConnection:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()

    def _create_conn(self) -> sqlite3.Connection:
        is_memory_db = self._db_path == ":memory:"
        connect_path = "file:ekb_control_plane?mode=memory&cache=shared" if is_memory_db else self._db_path
        conn = sqlite3.connect(
            connect_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,
            uri=is_memory_db,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    @staticmethod
    def _is_retryable_lock_error(error: sqlite3.OperationalError) -> bool:
        message = str(error).lower()
        return "database is locked" in message or "database schema is locked" in message

    def _with_retry(self, operation: Callable[[], _T]) -> _T:
        max_retries = 8
        for attempt in range(max_retries + 1):
            try:
                return operation()
            except sqlite3.OperationalError as error:
                if not self._is_retryable_lock_error(error) or attempt == max_retries:
                    raise
                time.sleep(min(0.8, 0.02 * (2**attempt)))
        raise RuntimeError("unreachable retry loop")

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._create_conn()
            self._local.conn = conn
        return conn

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._with_retry(lambda: self._conn().execute(sql, params))

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        return self._with_retry(lambda: self._conn().executescript(sql_script))

    def commit(self) -> None:
        self._with_retry(lambda: self._conn().commit())


class SQLiteControlPlaneStore:
    def __init__(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _ThreadLocalSQLiteConnection(str(path))
        self._instance_id = os.getenv(
            "EKB_RELAY_INSTANCE_ID",
            f"{os.getenv('HOSTNAME', 'host')}-{os.getpid()}",
        )
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")
        self._conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS skills (
                skill_name TEXT NOT NULL,
                version TEXT NOT NULL,
                owner TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                stage TEXT NOT NULL,
                allowed_tools_json TEXT NOT NULL,
                allowed_domains_json TEXT NOT NULL,
                residency_scope_json TEXT NOT NULL,
                input_schema_json TEXT NOT NULL,
                output_schema_json TEXT NOT NULL,
                changelog TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                PRIMARY KEY (skill_name, version)
            );

            CREATE TABLE IF NOT EXISTS audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                region_id TEXT NOT NULL,
                plant_id TEXT NOT NULL,
                user_or_agent_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                decision_reason TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS harness_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                quality_score REAL NOT NULL,
                safety_score REAL NOT NULL,
                regression_score REAL NOT NULL,
                latency_ms INTEGER NOT NULL,
                accepted INTEGER NOT NULL,
                reasons_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS outbox_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retries INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                claimed_by TEXT NOT NULL DEFAULT '',
                claimed_at TEXT,
                next_retry_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                published_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_outbox_status_id
              ON outbox_events(status, id);

            CREATE TABLE IF NOT EXISTS business_capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                capability_type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                owner TEXT NOT NULL,
                maturity TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(domain, capability_type, title)
            );

            CREATE TABLE IF NOT EXISTS connector_envelopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector_system TEXT NOT NULL,
                direction TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                region_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                status TEXT NOT NULL,
                replay_count INTEGER NOT NULL DEFAULT 0,
                last_replayed_at TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(connector_system, idempotency_key)
            );

            CREATE INDEX IF NOT EXISTS idx_connector_system_created
              ON connector_envelopes(connector_system, created_at);

            CREATE TABLE IF NOT EXISTS connector_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector_system TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                auth_config_json TEXT NOT NULL,
                timeout_ms INTEGER NOT NULL,
                pull_batch_size INTEGER NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(connector_system, profile_name)
            );

            CREATE TABLE IF NOT EXISTS connector_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector_system TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                cursor TEXT NOT NULL,
                watermark TEXT,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                UNIQUE(connector_system, profile_name)
            );

            CREATE TABLE IF NOT EXISTS connector_pull_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connector_system TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                mode TEXT NOT NULL,
                from_cursor TEXT,
                next_cursor TEXT NOT NULL,
                pulled_count INTEGER NOT NULL,
                accepted_count INTEGER NOT NULL,
                replayed_count INTEGER NOT NULL,
                sample_event_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE TABLE IF NOT EXISTS sub_agent_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                region_id TEXT NOT NULL,
                plant_id TEXT,
                supervisor_id TEXT NOT NULL,
                sub_agent_type TEXT NOT NULL,
                task_objective TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                result_payload_json TEXT NOT NULL,
                error TEXT,
                worker_id TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                completed_at TEXT,
                UNIQUE(tenant_id, idempotency_key)
            );

            CREATE INDEX IF NOT EXISTS idx_sub_agent_tasks_supervisor
              ON sub_agent_tasks(supervisor_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_sub_agent_tasks_status
              ON sub_agent_tasks(status, updated_at);

            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT NOT NULL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                status TEXT NOT NULL,
                page_count INTEGER NOT NULL DEFAULT 0,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_documents_tenant_created
              ON documents(tenant_id, created_at);

            CREATE TABLE IF NOT EXISTS document_chunks (
                chunk_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                chunk_type TEXT NOT NULL,
                parent_id TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                tokens INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                PRIMARY KEY (doc_id, chunk_id)
            );

            CREATE INDEX IF NOT EXISTS idx_document_chunks_doc_seq
              ON document_chunks(doc_id, seq);
            CREATE INDEX IF NOT EXISTS idx_document_chunks_type
              ON document_chunks(chunk_type);

            CREATE TABLE IF NOT EXISTS rbac_users (
                user_id TEXT NOT NULL PRIMARY KEY,
                role TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'group',
                department TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            );
            """
        )
        self._ensure_outbox_migration_columns()
        self._conn.commit()

    def _run_write(self, operation: Callable[[], _T]) -> _T:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self._conn.commit()
            return result
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _ensure_outbox_migration_columns(self) -> None:
        columns = self._conn.execute("PRAGMA table_info(outbox_events)").fetchall()
        column_names = {str(row["name"]) for row in columns}

        if "claimed_by" not in column_names:
            self._conn.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN claimed_by TEXT NOT NULL DEFAULT ''
                """
            )
        if "claimed_at" not in column_names:
            self._conn.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN claimed_at TEXT
                """
            )
        if "next_retry_at" not in column_names:
            self._conn.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN next_retry_at TEXT
                """
            )

        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_claimed
              ON outbox_events(status, claimed_by, claimed_at)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_retry
              ON outbox_events(status, next_retry_at, id)
            """
        )

    def list_skills(self) -> list[SkillRow]:
        rows = self._conn.execute(
            """
            SELECT skill_name, version, owner, risk_level, stage,
                   allowed_tools_json, allowed_domains_json, residency_scope_json,
                   input_schema_json, output_schema_json, changelog
            FROM skills
            ORDER BY skill_name, version
            """
        ).fetchall()
        return [self._row_to_skill(row) for row in rows]

    def create_skill(self, manifest: SkillManifest, stage: SkillStage) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO skills (
                    skill_name, version, owner, risk_level, stage,
                    allowed_tools_json, allowed_domains_json, residency_scope_json,
                    input_schema_json, output_schema_json, changelog
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.skill_name,
                    manifest.version,
                    manifest.owner,
                    manifest.risk_level.value,
                    stage.value,
                    json.dumps(manifest.allowed_tools, ensure_ascii=False),
                    json.dumps(manifest.allowed_domains, ensure_ascii=False),
                    json.dumps(manifest.residency_scope, ensure_ascii=False),
                    json.dumps(manifest.input_schema, ensure_ascii=False),
                    json.dumps(manifest.output_schema, ensure_ascii=False),
                    manifest.changelog,
                ),
            )

        self._run_write(_operation)

    def update_skill_stage(self, skill_name: str, version: str, stage: SkillStage) -> None:
        rowcount = 0

        def _operation() -> None:
            nonlocal rowcount
            cursor = self._conn.execute(
                """
                UPDATE skills
                SET stage = ?,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE skill_name = ? AND version = ?
                """,
                (stage.value, skill_name, version),
            )
            rowcount = cursor.rowcount

        self._run_write(_operation)
        if rowcount == 0:
            raise KeyError("skill not found")

    # ------------------------------------------------------------------
    # P0-② 文档流水线存储 + P0-④ RBAC 用户绑定
    # ------------------------------------------------------------------
    def upsert_document(self, doc: dict) -> None:
        if doc is None:
            raise ValueError("doc_required")

        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO documents (
                    doc_id, tenant_id, source_name, source_type, mime_type,
                    content_sha256, status, page_count, chunk_count, error,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    status = excluded.status,
                    page_count = excluded.page_count,
                    chunk_count = excluded.chunk_count,
                    error = excluded.error,
                    metadata_json = excluded.metadata_json,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (
                    doc.get("doc_id", ""),
                    doc.get("tenant_id", "group"),
                    doc.get("source_name", ""),
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

        self._run_write(_operation)

    def get_document(self, doc_id: str) -> dict | None:
        if not doc_id:
            return None
        row = self._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return self._document_row_to_dict(row) if row is not None else None

    def list_documents(self, tenant_id: str | None = None, limit: int = 50) -> list[dict]:
        effective_limit = max(1, min(int(limit or 50), 200))
        if tenant_id:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, effective_limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?",
                (effective_limit,),
            ).fetchall()
        return [self._document_row_to_dict(row) for row in rows]

    def replace_document_chunks(self, doc_id: str, chunks: list[dict]) -> None:
        if not doc_id:
            raise ValueError("doc_id_required")
        if chunks is None:
            chunks = []

        def _operation() -> None:
            self._conn.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
            for chunk in chunks:
                self._conn.execute(
                    """
                    INSERT INTO document_chunks (
                        chunk_id, doc_id, seq, chunk_type, parent_id,
                        content, tokens, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.get("chunk_id", ""),
                        doc_id,
                        int(chunk.get("seq", 0) or 0),
                        chunk.get("chunk_type", "text"),
                        chunk.get("parent_id", "") or "",
                        chunk.get("content", ""),
                        int(chunk.get("tokens", 0) or 0),
                        chunk.get("metadata_json", "{}") or "{}",
                    ),
                )

        self._run_write(_operation)

    def list_document_chunks(
        self, doc_id: str, chunk_type: str | None = None, limit: int = 200
    ) -> list[dict]:
        if not doc_id:
            return []
        effective_limit = max(1, min(int(limit or 200), 1000))
        if chunk_type:
            rows = self._conn.execute(
                """
                SELECT chunk_id, doc_id, seq, chunk_type, parent_id, content, tokens, metadata_json
                FROM document_chunks
                WHERE doc_id = ? AND chunk_type = ?
                ORDER BY seq LIMIT ?
                """,
                (doc_id, chunk_type, effective_limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT chunk_id, doc_id, seq, chunk_type, parent_id, content, tokens, metadata_json
                FROM document_chunks
                WHERE doc_id = ?
                ORDER BY seq LIMIT ?
                """,
                (doc_id, effective_limit),
            ).fetchall()
        result: list[dict] = []
        for row in rows or []:
            result.append(
                {
                    "chunk_id": row[0],
                    "doc_id": row[1],
                    "seq": row[2],
                    "chunk_type": row[3],
                    "parent_id": row[4],
                    "content": row[5],
                    "tokens": row[6],
                    "metadata": _json_loads_or_empty(row[7]),
                }
            )
        return result

    @staticmethod
    def _document_row_to_dict(row: Any) -> dict:
        columns = [
            "doc_id",
            "tenant_id",
            "source_name",
            "source_type",
            "mime_type",
            "content_sha256",
            "status",
            "page_count",
            "chunk_count",
            "error",
            "metadata_json",
            "created_at",
            "updated_at",
        ]
        doc = {key: row[index] for index, key in enumerate(columns)}
        doc["metadata"] = _json_loads_or_empty(doc.pop("metadata_json", "{}"))
        return doc

    def upsert_user(
        self, user_id: str, role: str, tenant_id: str = "group", department: str = ""
    ) -> None:
        if not user_id or not role:
            raise ValueError("user_id_and_role_required")

        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO rbac_users (user_id, role, tenant_id, department)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    role = excluded.role,
                    tenant_id = excluded.tenant_id,
                    department = excluded.department,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (user_id, role, tenant_id or "group", department or ""),
            )

        self._run_write(_operation)

    def get_user_role(self, user_id: str) -> str | None:
        if not user_id:
            return None
        row = self._conn.execute(
            "SELECT role FROM rbac_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row is not None else None

    def list_users(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT user_id, role, tenant_id, department, created_at, updated_at
            FROM rbac_users ORDER BY user_id
            """
        ).fetchall()
        return [
            {
                "user_id": row[0],
                "role": row[1],
                "tenant_id": row[2],
                "department": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows or []
        ]

    def delete_user(self, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id_required")

        def _operation() -> None:
            self._conn.execute("DELETE FROM rbac_users WHERE user_id = ?", (user_id,))

        self._run_write(_operation)

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
        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO audits (
                    tenant_id, region_id, plant_id, user_or_agent_id,
                    skill_name, skill_version, tool_name,
                    decision_reason, accepted, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

        self._run_write(_operation)

    def recent_audits(self, limit: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, tenant_id, region_id, plant_id, user_or_agent_id,
                   skill_name, skill_version, tool_name,
                   decision_reason, accepted, payload_json, created_at
            FROM audits
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "tenant_id": row["tenant_id"],
                    "region_id": row["region_id"],
                    "plant_id": row["plant_id"],
                    "user_or_agent_id": row["user_or_agent_id"],
                    "skill": f"{row['skill_name']}:{row['skill_version']}",
                    "tool": row["tool_name"],
                    "decision_reason": row["decision_reason"],
                    "accepted": bool(row["accepted"]),
                    "payload": json.loads(row["payload_json"]),
                    "created_at": row["created_at"],
                }
            )
        return result

    def append_harness_run(
        self,
        tenant_id: str,
        skill_name: str,
        skill_version: str,
        quality_score: float,
        safety_score: float,
        regression_score: float,
        latency_ms: int,
        accepted: bool,
        reasons: list[str],
    ) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO harness_runs (
                    tenant_id, skill_name, skill_version,
                    quality_score, safety_score, regression_score,
                    latency_ms, accepted, reasons_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    skill_name,
                    skill_version,
                    quality_score,
                    safety_score,
                    regression_score,
                    latency_ms,
                    1 if accepted else 0,
                    json.dumps(reasons, ensure_ascii=False),
                ),
            )

        self._run_write(_operation)

    def enqueue_outbox(self, event_type: str, payload: dict[str, Any]) -> int:
        event_id: int | None = None

        def _operation() -> None:
            nonlocal event_id
            cursor = self._conn.execute(
                """
                    INSERT INTO outbox_events (event_type, payload_json, next_retry_at)
                    VALUES (?, ?, (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
                    """,
                    (event_type, json.dumps(payload, ensure_ascii=False)),
            )
            if cursor.lastrowid is not None:
                event_id = int(cursor.lastrowid)

        self._run_write(_operation)
        if event_id is None:
            raise RuntimeError("failed to create outbox event")
        return event_id

    def claim_pending_outbox(self, limit: int, claim_timeout_seconds: int = 30) -> list[dict[str, Any]]:
        def _operation() -> list[dict[str, Any]]:
            # Reclaim events left in 'processing' by crashed claimers.
            self._conn.execute(
                """
                UPDATE outbox_events
                SET status = 'pending',
                    claimed_by = '',
                    claimed_at = NULL
                WHERE status = 'processing'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """
            )
            # Atomic claim: a single UPDATE decides the winners (id IN subquery +
            # status guard), so concurrent relay instances can never claim the same
            # event regardless of process boundaries. Mirrors the TiDB store.
            self._conn.execute(
                """
                UPDATE outbox_events
                SET status = 'processing',
                    claimed_by = ?,
                    claimed_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    next_retry_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+' || ? || ' seconds'))
                WHERE id IN (
                    SELECT id
                    FROM outbox_events
                    WHERE status = 'pending'
                      AND (next_retry_at IS NULL OR next_retry_at <= (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
                    ORDER BY id
                    LIMIT ?
                )
                  AND status = 'pending'
                """,
                (self._instance_id, claim_timeout_seconds, limit),
            )
            rows = self._conn.execute(
                """
                SELECT id, event_type, payload_json, retries
                FROM outbox_events
                WHERE status = 'processing' AND claimed_by = ?
                ORDER BY id
                LIMIT ?
                """,
                (self._instance_id, limit),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "payload": json.loads(row["payload_json"]),
                    "retries": row["retries"],
                }
                for row in rows
            ]

        return self._run_write(_operation)

    def next_pending_outbox(self, limit: int) -> list[dict[str, Any]]:
        return self.claim_pending_outbox(limit=limit)

    def mark_outbox_published(self, event_id: int) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                UPDATE outbox_events
                SET status = 'published',
                    claimed_by = '',
                    claimed_at = NULL,
                    published_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id = ?
                """,
                (event_id,),
            )

        self._run_write(_operation)

    def mark_outbox_failed(self, event_id: int, error: str) -> None:
        retries_row = self._conn.execute(
            "SELECT retries FROM outbox_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        current_retries = int(retries_row["retries"]) if retries_row is not None else 0
        next_retry_seconds = min(300, int(2 ** min(8, current_retries + 1)))
        def _operation() -> None:
            self._conn.execute(
                """
                UPDATE outbox_events
                SET retries = retries + 1,
                    last_error = ?,
                    claimed_by = '',
                    claimed_at = NULL,
                    next_retry_at = CASE
                        WHEN retries + 1 >= 10 THEN NULL
                        ELSE (strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+' || ? || ' seconds'))
                    END,
                    status = CASE WHEN retries + 1 >= 10 THEN 'dead' ELSE 'pending' END
                WHERE id = ?
                """,
                (error[:500], next_retry_seconds, event_id),
            )

        self._run_write(_operation)

    def outbox_stats(self) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM outbox_events
            GROUP BY status
            """
        ).fetchall()
        stats: dict[str, int] = {"pending": 0, "processing": 0, "published": 0, "dead": 0}
        for row in rows:
            stats[str(row["status"])] = int(row["count"])
        return stats

    def outbox_claim_instance_id(self) -> str:
        return self._instance_id

    def recent_outbox_events(self, limit: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, event_type, status, retries, last_error, created_at, published_at
            FROM outbox_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            items.append(
                {
                    "id": int(row["id"]),
                    "event_type": str(row["event_type"]),
                    "status": str(row["status"]),
                    "retries": int(row["retries"]),
                    "last_error": str(row["last_error"]),
                    "created_at": str(row["created_at"]),
                    "published_at": str(row["published_at"]) if row["published_at"] is not None else None,
                }
            )
        return items

    def upsert_business_capability(self, capability: BusinessCapabilityManifest) -> int:
        capability_id: int | None = None

        def _operation() -> None:
            nonlocal capability_id
            cursor = self._conn.execute(
                """
                INSERT INTO business_capabilities (
                    domain, capability_type, title, description, owner, maturity,
                    tags_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain, capability_type, title)
                DO UPDATE SET
                    description = excluded.description,
                    owner = excluded.owner,
                    maturity = excluded.maturity,
                    tags_json = excluded.tags_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
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
            row_id = cursor.lastrowid
            if row_id is not None:
                capability_id = int(row_id)
                return

            existing = self._conn.execute(
                """
                SELECT id FROM business_capabilities
                WHERE domain = ? AND capability_type = ? AND title = ?
                """,
                (capability.domain.value, capability.capability_type, capability.title),
            ).fetchone()
            if existing is None:
                raise RuntimeError("failed to upsert business capability")
            capability_id = int(existing["id"])

        self._run_write(_operation)
        if capability_id is None:
            raise RuntimeError("failed to upsert business capability")
        return capability_id

    def list_business_capabilities(
        self,
        domain: BusinessDomain | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[BusinessCapabilityManifest]:
        sql = (
            "SELECT domain, capability_type, title, description, owner, maturity, tags_json, metadata_json "
            "FROM business_capabilities"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain.value)
        if query:
            # Escape LIKE wildcards so user input cannot widen the match (\ is the escape char).
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR capability_type LIKE ? ESCAPE '\\')"
            )
            like = f"%{escaped}%"
            params.extend([like, like, like])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY domain, capability_type, title LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, tuple(params)).fetchall()
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
                    tags=json.loads(row["tags_json"]),
                    metadata=json.loads(row["metadata_json"]),
                )
            )
        return result

    def persist_connector_envelope(
        self,
        envelope: ConnectorEnvelope,
        status: ConnectorRunStatus,
    ) -> tuple[int, bool]:
        inserted = False
        row_id: int | None = None

        def _operation() -> None:
            nonlocal inserted, row_id
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO connector_envelopes (
                    connector_system, direction, tenant_id, region_id, source_id,
                    event_type, occurred_at, idempotency_key,
                    payload_json, metadata_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    status.value,
                ),
            )
            inserted = cursor.rowcount == 1
            row = self._conn.execute(
                """
                SELECT id FROM connector_envelopes
                WHERE connector_system = ? AND idempotency_key = ?
                """,
                (envelope.connector_system.value, envelope.idempotency_key),
            ).fetchone()
            if row is None:
                raise RuntimeError("failed to persist connector envelope")
            row_id = int(row["id"])

        self._run_write(_operation)
        if row_id is None:
            raise RuntimeError("failed to persist connector envelope")
        return row_id, inserted

    def update_connector_status(self, row_id: int, status: ConnectorRunStatus) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                UPDATE connector_envelopes
                SET status = ?,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id = ?
                """,
                (status.value, row_id),
            )

        self._run_write(_operation)

    def list_connector_envelopes(
        self,
        connector_system: ConnectorSystem | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, connector_system, direction, tenant_id, region_id, source_id, "
            "event_type, occurred_at, idempotency_key, payload_json, metadata_json "
            "FROM connector_envelopes"
        )
        params: list[Any] = []
        if connector_system is not None:
            sql += " WHERE connector_system = ?"
            params.append(connector_system.value)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, tuple(params)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": int(row["id"]),
                    "envelope": ConnectorEnvelope(
                        connector_system=ConnectorSystem(row["connector_system"]),
                        direction=ConnectorDirection(row["direction"]),
                        tenant_id=row["tenant_id"],
                        region_id=row["region_id"],
                        source_id=row["source_id"],
                        event_type=row["event_type"],
                        occurred_at=row["occurred_at"],
                        idempotency_key=row["idempotency_key"],
                        payload=json.loads(row["payload_json"]),
                        metadata=json.loads(row["metadata_json"]),
                    ),
                }
            )
        return result

    def mark_connector_replayed(self, row_id: int, status: ConnectorRunStatus) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                UPDATE connector_envelopes
                SET replay_count = replay_count + 1,
                    status = ?,
                    last_replayed_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE id = ?
                """,
                (status.value, row_id),
            )

        self._run_write(_operation)

    def upsert_connector_profile(self, profile: ConnectorProfile) -> int:
        sanitized_metadata = {k: v for k, v in profile.metadata.items() if k != "adapter_type"}
        serialized_metadata = {**sanitized_metadata, "adapter_type": profile.adapter_type}
        profile_id: int | None = None

        def _operation() -> None:
            nonlocal profile_id
            cursor = self._conn.execute(
                """
                INSERT INTO connector_profiles (
                    connector_system, profile_name, base_url, auth_type,
                    auth_config_json, timeout_ms, pull_batch_size, status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_system, profile_name)
                DO UPDATE SET
                    base_url = excluded.base_url,
                    auth_type = excluded.auth_type,
                    auth_config_json = excluded.auth_config_json,
                    timeout_ms = excluded.timeout_ms,
                    pull_batch_size = excluded.pull_batch_size,
                    status = excluded.status,
                    metadata_json = excluded.metadata_json,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (
                    profile.connector_system.value,
                    profile.profile_name,
                    profile.base_url,
                    profile.auth_type.value,
                    json.dumps(profile.auth_config, ensure_ascii=False),
                    profile.timeout_ms,
                    profile.pull_batch_size,
                    profile.status.value,
                    json.dumps(serialized_metadata, ensure_ascii=False),
                ),
            )
            row = self._conn.execute(
                """
                SELECT id FROM connector_profiles
                WHERE connector_system = ? AND profile_name = ?
                """,
                (profile.connector_system.value, profile.profile_name),
            ).fetchone()
            if row is not None:
                profile_id = int(row["id"])
                return

            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("failed to upsert connector profile")
            profile_id = int(row_id)

        self._run_write(_operation)
        if profile_id is None:
            raise RuntimeError("failed to upsert connector profile")
        return profile_id

    def list_connector_profiles(
        self,
        connector_system: ConnectorSystem | None,
        limit: int,
    ) -> list[ConnectorProfile]:
        sql = (
            "SELECT connector_system, profile_name, base_url, auth_type, auth_config_json, "
            "timeout_ms, pull_batch_size, status, metadata_json FROM connector_profiles"
        )
        params: list[Any] = []
        if connector_system is not None:
            sql += " WHERE connector_system = ?"
            params.append(connector_system.value)
        sql += " ORDER BY connector_system, profile_name LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, tuple(params)).fetchall()
        result: list[ConnectorProfile] = []
        for row in rows:
            result.append(
                ConnectorProfile(
                    connector_system=ConnectorSystem(row["connector_system"]),
                    profile_name=row["profile_name"],
                    base_url=row["base_url"],
                    auth_type=ConnectorAuthType(row["auth_type"]),
                    auth_config=json.loads(row["auth_config_json"]),
                    timeout_ms=int(row["timeout_ms"]),
                    pull_batch_size=int(row["pull_batch_size"]),
                    status=ConnectorProfileStatus(row["status"]),
                    metadata={k: v for k, v in json.loads(row["metadata_json"]).items() if k != "adapter_type"},
                    adapter_type=ConnectorAdapterType(
                        json.loads(row["metadata_json"]).get("adapter_type", "generic")
                    ),
                )
            )
        return result

    def get_connector_profile(self, connector_system: ConnectorSystem, profile_name: str) -> ConnectorProfile | None:
        row = self._conn.execute(
            """
            SELECT connector_system, profile_name, base_url, auth_type, auth_config_json,
                   timeout_ms, pull_batch_size, status, metadata_json
            FROM connector_profiles
            WHERE connector_system = ? AND profile_name = ?
            """,
            (connector_system.value, profile_name),
        ).fetchone()
        if row is None:
            return None
        metadata_raw = json.loads(row["metadata_json"])
        adapter_type = metadata_raw.get("adapter_type", "generic")
        sanitized_metadata = {k: v for k, v in metadata_raw.items() if k != "adapter_type"}
        return ConnectorProfile(
            connector_system=ConnectorSystem(row["connector_system"]),
            profile_name=row["profile_name"],
            base_url=row["base_url"],
            auth_type=ConnectorAuthType(row["auth_type"]),
            auth_config=json.loads(row["auth_config_json"]),
            timeout_ms=int(row["timeout_ms"]),
            pull_batch_size=int(row["pull_batch_size"]),
            status=ConnectorProfileStatus(row["status"]),
            metadata=sanitized_metadata,
            adapter_type=ConnectorAdapterType(adapter_type),
        )

    def upsert_connector_checkpoint(
        self,
        connector_system: ConnectorSystem,
        profile_name: str,
        cursor: str,
        watermark: str | None,
    ) -> None:
        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO connector_checkpoints (connector_system, profile_name, cursor, watermark)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(connector_system, profile_name)
                DO UPDATE SET
                    cursor = excluded.cursor,
                    watermark = excluded.watermark,
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                """,
                (connector_system.value, profile_name, cursor, watermark),
            )

        self._run_write(_operation)

    def get_connector_checkpoint(self, connector_system: ConnectorSystem, profile_name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT connector_system, profile_name, cursor, watermark, updated_at
            FROM connector_checkpoints
            WHERE connector_system = ? AND profile_name = ?
            """,
            (connector_system.value, profile_name),
        ).fetchone()
        if row is None:
            return None
        return {
            "connector_system": row["connector_system"],
            "profile_name": row["profile_name"],
            "cursor": row["cursor"],
            "watermark": row["watermark"],
            "updated_at": row["updated_at"],
        }

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
        sample_event_ids: list[str],
    ) -> int:
        pull_run_id: int | None = None

        def _operation() -> None:
            nonlocal pull_run_id
            cursor = self._conn.execute(
                """
                INSERT INTO connector_pull_runs (
                    connector_system, profile_name, mode, from_cursor, next_cursor,
                    pulled_count, accepted_count, replayed_count, sample_event_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(sample_event_ids, ensure_ascii=False),
                ),
            )
            row_id = cursor.lastrowid
            if row_id is None:
                raise RuntimeError("failed to append connector pull run")
            pull_run_id = int(row_id)

        self._run_write(_operation)
        if pull_run_id is None:
            raise RuntimeError("failed to append connector pull run")
        return pull_run_id

    @staticmethod
    def _row_to_skill(row: sqlite3.Row) -> SkillRow:
        manifest = SkillManifest(
            skill_name=row["skill_name"],
            version=row["version"],
            owner=row["owner"],
            risk_level=row["risk_level"],
            allowed_tools=json.loads(row["allowed_tools_json"]),
            allowed_domains=json.loads(row["allowed_domains_json"]),
            residency_scope=json.loads(row["residency_scope_json"]),
            input_schema=json.loads(row["input_schema_json"]),
            output_schema=json.loads(row["output_schema_json"]),
            changelog=row["changelog"],
        )
        return SkillRow(manifest=manifest, stage=SkillStage(row["stage"]))

    def get_sub_agent_task_by_idempotency(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> SubAgentTaskRecord | None:
        row = self._conn.execute(
            """
            SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                   supervisor_id, sub_agent_type, task_objective, status,
                   attempt_count, result_payload_json, error, worker_id,
                   created_at, updated_at, completed_at
            FROM sub_agent_tasks
            WHERE tenant_id = ? AND idempotency_key = ?
            """,
            (tenant_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_sub_agent_task(row)

    def create_sub_agent_task(
        self,
        task_id: str,
        idempotency_key: str,
        tenant_id: str,
        region_id: str,
        plant_id: str | None,
        supervisor_id: str,
        sub_agent_type: str,
        task_objective: str,
    ) -> SubAgentTaskRecord:
        def _operation() -> None:
            self._conn.execute(
                """
                INSERT INTO sub_agent_tasks (
                    task_id, idempotency_key, tenant_id, region_id, plant_id,
                    supervisor_id, sub_agent_type, task_objective, status,
                    attempt_count, result_payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    idempotency_key,
                    tenant_id,
                    region_id,
                    plant_id,
                    supervisor_id,
                    sub_agent_type,
                    task_objective,
                    SubAgentTaskStatus.queued.value,
                    0,
                    json.dumps({}, ensure_ascii=False),
                ),
            )

        self._run_write(_operation)
        created = self.get_sub_agent_task(task_id=task_id)
        if created is None:
            raise RuntimeError("failed to create sub agent task")
        return created

    def get_sub_agent_task(self, task_id: str) -> SubAgentTaskRecord | None:
        row = self._conn.execute(
            """
            SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                   supervisor_id, sub_agent_type, task_objective, status,
                   attempt_count, result_payload_json, error, worker_id,
                   created_at, updated_at, completed_at
            FROM sub_agent_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_sub_agent_task(row)

    def list_sub_agent_tasks_by_supervisor(
        self,
        supervisor_id: str,
        limit: int,
    ) -> list[SubAgentTaskRecord]:
        rows = self._conn.execute(
            """
            SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                   supervisor_id, sub_agent_type, task_objective, status,
                   attempt_count, result_payload_json, error, worker_id,
                   created_at, updated_at, completed_at
            FROM sub_agent_tasks
            WHERE supervisor_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (supervisor_id, limit),
        ).fetchall()
        return [self._row_to_sub_agent_task(row) for row in rows]

    def update_sub_agent_task_status(
        self,
        task_id: str,
        status: SubAgentTaskStatus,
        *,
        result_payload: dict[str, Any] | None = None,
        error: str | None = None,
        worker_id: str | None = None,
        increment_attempt: bool = False,
    ) -> None:
        def _operation() -> None:
            if increment_attempt:
                self._conn.execute(
                    """
                    UPDATE sub_agent_tasks
                    SET status = ?,
                        attempt_count = attempt_count + 1,
                        worker_id = COALESCE(?, worker_id),
                        updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    WHERE task_id = ?
                    """,
                    (status.value, worker_id, task_id),
                )
                return

            self._conn.execute(
                """
                UPDATE sub_agent_tasks
                SET status = ?,
                    result_payload_json = COALESCE(?, result_payload_json),
                    error = ?,
                    worker_id = COALESCE(?, worker_id),
                    updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    completed_at = CASE
                        WHEN ? IN ('completed', 'failed', 'cancelled') THEN (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        ELSE completed_at
                    END
                WHERE task_id = ?
                """,
                (
                    status.value,
                    json.dumps(result_payload, ensure_ascii=False) if result_payload is not None else None,
                    error,
                    worker_id,
                    status.value,
                    task_id,
                ),
            )

        self._run_write(_operation)

    @staticmethod
    def _row_to_sub_agent_task(row: sqlite3.Row) -> SubAgentTaskRecord:
        return SubAgentTaskRecord(
            task_id=str(row["task_id"]),
            idempotency_key=str(row["idempotency_key"]),
            tenant_id=str(row["tenant_id"]),
            region_id=str(row["region_id"]),
            plant_id=row["plant_id"],
            supervisor_id=str(row["supervisor_id"]),
            sub_agent_type=str(row["sub_agent_type"]),
            task_objective=str(row["task_objective"]),
            status=SubAgentTaskStatus(str(row["status"])),
            attempt_count=int(row["attempt_count"]),
            result_payload=json.loads(str(row["result_payload_json"])),
            error=row["error"],
            worker_id=row["worker_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=row["completed_at"],
        )

class ReplicaRoutingStore:
    """Read/write routing wrapper: read methods go to the replica, the rest to primary.

    Implements the read-write separation layer (review §10): with SQLite both
    stores share one file (no lag); with TiDB the replica is a follower
    endpoint (eventual consistency, configurable via EKB_TIDB_READ_HOST).
    The outbox relay must keep using the primary store directly.
    """

    READ_METHODS = frozenset({
        "list_skills",
        "get_sub_agent_task",
        "list_sub_agent_tasks_by_supervisor",
        "recent_audits",
        "list_business_capabilities",
        "outbox_stats",
        "outbox_claim_instance_id",
    })

    def __init__(self, primary: Any, replica: Any) -> None:
        self._primary = primary
        self._replica = replica

    def __getattr__(self, name: str) -> Any:
        target = self._replica if name in ReplicaRoutingStore.READ_METHODS else self._primary
        return getattr(target, name)
