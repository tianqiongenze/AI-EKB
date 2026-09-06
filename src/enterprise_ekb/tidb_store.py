from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from enterprise_ekb.schemas import (
    BusinessCapabilityManifest,
    BusinessDomain,
    CapabilityMaturity,
    ConnectorAdapterType,
    ConnectorAuthType,
    ConnectorEnvelope,
    ConnectorDirection,
    ConnectorProfile,
    ConnectorProfileStatus,
    ConnectorRunStatus,
    ConnectorSystem,
    SkillManifest,
    SkillStage,
    SubAgentTaskRecord,
    SubAgentTaskStatus,
)
from enterprise_ekb.migrator import TiDBMigrator
from enterprise_ekb.storage import SQLiteControlPlaneStore, SkillRow

try:
    import pymysql
except ImportError:
    pymysql = None


class _ThreadLocalPyMySQLConnection:
    def __init__(self, connect_kwargs: dict[str, Any]) -> None:
        if pymysql is None:
            raise RuntimeError("pymysql is required for TiDB mode")
        self._connect_kwargs = connect_kwargs
        self._local = threading.local()

    def _connect(self) -> Any:
        assert pymysql is not None
        return pymysql.connect(**self._connect_kwargs)

    def _current(self) -> Any:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
            return conn

        try:
            conn.ping(reconnect=True)
        except Exception:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._current(), name)


class TiDBControlPlaneStore(SQLiteControlPlaneStore):
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
    ) -> None:
        if pymysql is None:
            raise RuntimeError("pymysql is required for TiDB mode")
        connect_kwargs: dict[str, Any] = dict(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=False,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        self._conn = _ThreadLocalPyMySQLConnection(connect_kwargs)
        self._instance_id = os.getenv(
            "EKB_RELAY_INSTANCE_ID",
            f"{os.getenv('HOSTNAME', 'host')}-{os.getpid()}",
        )
        self._run_migrations()

    def _run_migrations(self) -> None:
        migrations_dir = Path(__file__).with_name("migrations")
        migrator = TiDBMigrator(connection=self._conn, migrations_dir=str(migrations_dir))
        migrator.migrate()
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(128) NOT NULL DEFAULT ''
                """
            )
            cursor.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP NULL
                """
            )
            cursor.execute(
                """
                ALTER TABLE outbox_events
                ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP NULL
                """
            )
            cursor.execute(
                """
                ALTER TABLE outbox_events
                ADD INDEX IF NOT EXISTS idx_outbox_claimed (status, claimed_by, claimed_at)
                """
            )
            cursor.execute(
                """
                ALTER TABLE outbox_events
                ADD INDEX IF NOT EXISTS idx_outbox_retry (status, next_retry_at, id)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS business_capabilities (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    domain VARCHAR(64) NOT NULL,
                    capability_type VARCHAR(128) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    owner VARCHAR(191) NOT NULL,
                    maturity VARCHAR(32) NOT NULL,
                    tags_json JSON NOT NULL,
                    metadata_json JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_domain_capability (domain, capability_type, title),
                    KEY idx_domain_maturity (domain, maturity)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_envelopes (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    connector_system VARCHAR(64) NOT NULL,
                    direction VARCHAR(32) NOT NULL,
                    tenant_id VARCHAR(191) NOT NULL,
                    region_id VARCHAR(64) NOT NULL,
                    source_id VARCHAR(191) NOT NULL,
                    event_type VARCHAR(191) NOT NULL,
                    occurred_at VARCHAR(64) NOT NULL,
                    idempotency_key VARCHAR(191) NOT NULL,
                    payload_json JSON NOT NULL,
                    metadata_json JSON NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    replay_count INT NOT NULL DEFAULT 0,
                    last_replayed_at TIMESTAMP NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_connector_idempotency (connector_system, idempotency_key),
                    KEY idx_connector_system_created (connector_system, created_at)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_profiles (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    connector_system VARCHAR(64) NOT NULL,
                    profile_name VARCHAR(191) NOT NULL,
                    base_url VARCHAR(1024) NOT NULL,
                    auth_type VARCHAR(64) NOT NULL,
                    auth_config_json JSON NOT NULL,
                    timeout_ms INT NOT NULL,
                    pull_batch_size INT NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    metadata_json JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_connector_profile (connector_system, profile_name)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_checkpoints (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    connector_system VARCHAR(64) NOT NULL,
                    profile_name VARCHAR(191) NOT NULL,
                    `cursor` VARCHAR(1024) NOT NULL,
                    watermark VARCHAR(128),
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_connector_checkpoint (connector_system, profile_name)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS connector_pull_runs (
                    id BIGINT NOT NULL AUTO_INCREMENT,
                    connector_system VARCHAR(64) NOT NULL,
                    profile_name VARCHAR(191) NOT NULL,
                    mode VARCHAR(32) NOT NULL,
                    from_cursor VARCHAR(1024),
                    next_cursor VARCHAR(1024) NOT NULL,
                    pulled_count INT NOT NULL,
                    accepted_count INT NOT NULL,
                    replayed_count INT NOT NULL,
                    sample_event_ids_json JSON NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id),
                    KEY idx_connector_pull_runs (connector_system, profile_name, created_at)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sub_agent_tasks (
                    id BIGINT NOT NULL AUTO_INCREMENT,
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
                    result_payload_json JSON NOT NULL,
                    error TEXT,
                    worker_id VARCHAR(191),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP NULL,
                    PRIMARY KEY (id),
                    UNIQUE KEY uk_sub_agent_task_id (task_id),
                    UNIQUE KEY uk_sub_agent_tenant_idem (tenant_id, idempotency_key),
                    KEY idx_sub_agent_supervisor_created (supervisor_id, created_at),
                    KEY idx_sub_agent_status_updated (status, updated_at)
                )
                """
            )
        self._conn.commit()

    def get_sub_agent_task_by_idempotency(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> SubAgentTaskRecord | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                       supervisor_id, sub_agent_type, task_objective, status,
                       attempt_count, result_payload_json, error, worker_id,
                       created_at, updated_at, completed_at
                FROM sub_agent_tasks
                WHERE tenant_id = %s AND idempotency_key = %s
                """,
                (tenant_id, idempotency_key),
            )
            row = cursor.fetchone()
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
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sub_agent_tasks (
                    task_id, idempotency_key, tenant_id, region_id, plant_id,
                    supervisor_id, sub_agent_type, task_objective, status,
                    attempt_count, result_payload_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        self._conn.commit()
        created = self.get_sub_agent_task(task_id=task_id)
        if created is None:
            raise RuntimeError("failed to create sub agent task")
        return created

    def get_sub_agent_task(self, task_id: str) -> SubAgentTaskRecord | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                       supervisor_id, sub_agent_type, task_objective, status,
                       attempt_count, result_payload_json, error, worker_id,
                       created_at, updated_at, completed_at
                FROM sub_agent_tasks
                WHERE task_id = %s
                """,
                (task_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_sub_agent_task(row)

    def list_sub_agent_tasks_by_supervisor(
        self,
        supervisor_id: str,
        limit: int,
    ) -> list[SubAgentTaskRecord]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT task_id, idempotency_key, tenant_id, region_id, plant_id,
                       supervisor_id, sub_agent_type, task_objective, status,
                       attempt_count, result_payload_json, error, worker_id,
                       created_at, updated_at, completed_at
                FROM sub_agent_tasks
                WHERE supervisor_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (supervisor_id, limit),
            )
            rows = cursor.fetchall()
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
        with self._conn.cursor() as cursor:
            if increment_attempt:
                cursor.execute(
                    """
                    UPDATE sub_agent_tasks
                    SET status = %s,
                        attempt_count = attempt_count + 1,
                        worker_id = COALESCE(%s, worker_id)
                    WHERE task_id = %s
                    """,
                    (status.value, worker_id, task_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE sub_agent_tasks
                    SET status = %s,
                        result_payload_json = COALESCE(%s, result_payload_json),
                        error = %s,
                        worker_id = COALESCE(%s, worker_id),
                        completed_at = CASE
                            WHEN %s IN ('completed', 'failed', 'cancelled') THEN CURRENT_TIMESTAMP
                            ELSE completed_at
                        END
                    WHERE task_id = %s
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
        self._conn.commit()

    def list_skills(self) -> list[SkillRow]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT skill_name, version, owner, risk_level, stage,
                       allowed_tools_json, allowed_domains_json, residency_scope_json,
                       input_schema_json, output_schema_json, changelog
                FROM skills
                ORDER BY skill_name, version
                """
            )
            rows = cursor.fetchall()
        result: list[SkillRow] = []
        for row in rows:
            result.append(
                SkillRow(
                    manifest=SkillManifest(
                        skill_name=row["skill_name"],
                        version=row["version"],
                        owner=row["owner"],
                        risk_level=row["risk_level"],
                        allowed_tools=self._decode_json(row["allowed_tools_json"]),
                        allowed_domains=self._decode_json(row["allowed_domains_json"]),
                        residency_scope=self._decode_json(row["residency_scope_json"]),
                        input_schema=self._decode_json(row["input_schema_json"]),
                        output_schema=self._decode_json(row["output_schema_json"]),
                        changelog=row["changelog"],
                    ),
                    stage=SkillStage(row["stage"]),
                )
            )
        return result

    def create_skill(self, manifest: SkillManifest, stage: SkillStage) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO skills (
                    skill_name, version, owner, risk_level, stage,
                    allowed_tools_json, allowed_domains_json, residency_scope_json,
                    input_schema_json, output_schema_json, changelog
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        self._conn.commit()

    def update_skill_stage(self, skill_name: str, version: str, stage: SkillStage) -> None:
        with self._conn.cursor() as cursor:
            affected = cursor.execute(
                """
                UPDATE skills
                SET stage = %s
                WHERE skill_name = %s AND version = %s
                """,
                (stage.value, skill_name, version),
            )
        self._conn.commit()
        if affected == 0:
            raise KeyError("skill not found")

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
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audits (
                    tenant_id, region_id, plant_id, user_or_agent_id,
                    skill_name, skill_version, tool_name,
                    decision_reason, accepted, payload_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        self._conn.commit()

    def recent_audits(self, limit: int) -> list[dict[str, Any]]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tenant_id, region_id, plant_id, user_or_agent_id,
                       skill_name, skill_version, tool_name,
                       decision_reason, accepted, payload_json, created_at
                FROM audits
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = self._decode_json(row["payload_json"])
            result.append(
                {
                    "id": int(row["id"]),
                    "tenant_id": row["tenant_id"],
                    "region_id": row["region_id"],
                    "plant_id": row["plant_id"],
                    "user_or_agent_id": row["user_or_agent_id"],
                    "skill": f"{row['skill_name']}:{row['skill_version']}",
                    "tool": row["tool_name"],
                    "decision_reason": row["decision_reason"],
                    "accepted": bool(row["accepted"]),
                    "payload": payload,
                    "created_at": str(row["created_at"]),
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
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO harness_runs (
                    tenant_id, skill_name, skill_version,
                    quality_score, safety_score, regression_score,
                    latency_ms, accepted, reasons_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        self._conn.commit()

    def enqueue_outbox(self, event_type: str, payload: dict[str, Any]) -> int:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO outbox_events (
                    event_type, payload_json, status, retries, last_error, next_retry_at
                )
                VALUES (%s, %s, 'pending', 0, '', CURRENT_TIMESTAMP)
                """,
                (event_type, json.dumps(payload, ensure_ascii=False)),
            )
            event_id = cursor.lastrowid
        self._conn.commit()
        if event_id is None:
            raise RuntimeError("failed to create outbox event")
        return int(event_id)

    def claim_pending_outbox(self, limit: int, claim_timeout_seconds: int = 30) -> list[dict[str, Any]]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET status = 'pending',
                    claimed_by = '',
                    claimed_at = NULL
                WHERE status = 'processing'
                  AND next_retry_at IS NOT NULL
                  AND next_retry_at <= CURRENT_TIMESTAMP
                """
            )
            cursor.execute(
                """
                UPDATE outbox_events
                SET status = 'processing',
                    claimed_by = %s,
                    claimed_at = CURRENT_TIMESTAMP,
                    next_retry_at = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND)
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id
                        FROM outbox_events
                        WHERE status = 'pending'
                          AND (next_retry_at IS NULL OR next_retry_at <= CURRENT_TIMESTAMP)
                        ORDER BY id
                        LIMIT %s
                    ) AS claim_candidates
                )
                  AND status = 'pending'
                """,
                (self._instance_id, claim_timeout_seconds, limit),
            )
            cursor.execute(
                """
                SELECT id, event_type, payload_json, retries
                FROM outbox_events
                WHERE status = 'processing' AND claimed_by = %s
                ORDER BY id
                LIMIT %s
                """,
                (self._instance_id, limit),
            )
            rows = cursor.fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            events.append(
                {
                    "id": int(row["id"]),
                    "event_type": row["event_type"],
                    "payload": self._decode_json(row["payload_json"]),
                    "retries": int(row["retries"]),
                }
            )
        return events

    def next_pending_outbox(self, limit: int) -> list[dict[str, Any]]:
        return self.claim_pending_outbox(limit=limit)

    def mark_outbox_published(self, event_id: int) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET status = 'published',
                    claimed_by = '',
                    claimed_at = NULL,
                    published_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (event_id,),
            )
        self._conn.commit()

    def mark_outbox_failed(self, event_id: int, error: str) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT retries FROM outbox_events WHERE id = %s", (event_id,))
            row = cursor.fetchone()
            current_retries = int(row["retries"]) if row is not None else 0
        next_retry_seconds = min(300, int(2 ** min(8, current_retries + 1)))
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET retries = retries + 1,
                    last_error = %s,
                    claimed_by = '',
                    claimed_at = NULL,
                    next_retry_at = CASE
                        WHEN retries + 1 >= 10 THEN NULL
                        ELSE DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND)
                    END,
                    status = CASE WHEN retries + 1 >= 10 THEN 'dead' ELSE 'pending' END
                WHERE id = %s
                """,
                (error[:500], next_retry_seconds, event_id),
            )
        self._conn.commit()

    def outbox_stats(self) -> dict[str, int]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM outbox_events
                GROUP BY status
                """
            )
            rows = cursor.fetchall()
        stats: dict[str, int] = {"pending": 0, "processing": 0, "published": 0, "dead": 0}
        for row in rows:
            stats[str(row["status"])] = int(row["count"])
        return stats

    def outbox_claim_instance_id(self) -> str:
        return self._instance_id

    def recent_outbox_events(self, limit: int) -> list[dict[str, Any]]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, event_type, status, retries, last_error, created_at, published_at
                FROM outbox_events
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
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
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO business_capabilities (
                    domain, capability_type, title, description, owner, maturity,
                    tags_json, metadata_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    description = VALUES(description),
                    owner = VALUES(owner),
                    maturity = VALUES(maturity),
                    tags_json = VALUES(tags_json),
                    metadata_json = VALUES(metadata_json),
                    updated_at = CURRENT_TIMESTAMP
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
            cursor.execute(
                """
                SELECT id FROM business_capabilities
                WHERE domain = %s AND capability_type = %s AND title = %s
                """,
                (capability.domain.value, capability.capability_type, capability.title),
            )
            row = cursor.fetchone()
        self._conn.commit()
        if row is None:
            raise RuntimeError("failed to upsert business capability")
        return int(row["id"])

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
            clauses.append("domain = %s")
            params.append(domain.value)
        if query:
            # Escape LIKE wildcards so user input cannot widen the match (\ is the escape char).
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append(
                "(title LIKE %s ESCAPE '\\' OR description LIKE %s ESCAPE '\\' OR capability_type LIKE %s ESCAPE '\\')"
            )
            like = f"%{escaped}%"
            params.extend([like, like, like])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY domain, capability_type, title LIMIT %s"
        params.append(limit)

        with self._conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

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
                    tags=self._decode_json(row["tags_json"]),
                    metadata=self._decode_json(row["metadata_json"]),
                )
            )
        return result

    def persist_connector_envelope(
        self,
        envelope: ConnectorEnvelope,
        status: ConnectorRunStatus,
    ) -> tuple[int, bool]:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO connector_envelopes (
                    connector_system, direction, tenant_id, region_id, source_id,
                    event_type, occurred_at, idempotency_key,
                    payload_json, metadata_json, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
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
            row_id = cursor.lastrowid
            inserted = cursor.rowcount == 1
        self._conn.commit()
        if row_id is None:
            raise RuntimeError("failed to persist connector envelope")
        return int(row_id), inserted

    def update_connector_status(self, row_id: int, status: ConnectorRunStatus) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE connector_envelopes
                SET status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status.value, row_id),
            )
        self._conn.commit()

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
            sql += " WHERE connector_system = %s"
            params.append(connector_system.value)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)

        with self._conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

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
                        payload=self._decode_json(row["payload_json"]),
                        metadata=self._decode_json(row["metadata_json"]),
                    ),
                }
            )
        return result

    def mark_connector_replayed(self, row_id: int, status: ConnectorRunStatus) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE connector_envelopes
                SET replay_count = replay_count + 1,
                    status = %s,
                    last_replayed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (status.value, row_id),
            )
        self._conn.commit()

    def upsert_connector_profile(self, profile: ConnectorProfile) -> int:
        sanitized_metadata = {k: v for k, v in profile.metadata.items() if k != "adapter_type"}
        serialized_metadata = {**sanitized_metadata, "adapter_type": profile.adapter_type}
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO connector_profiles (
                    connector_system, profile_name, base_url, auth_type,
                    auth_config_json, timeout_ms, pull_batch_size, status, metadata_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    base_url = VALUES(base_url),
                    auth_type = VALUES(auth_type),
                    auth_config_json = VALUES(auth_config_json),
                    timeout_ms = VALUES(timeout_ms),
                    pull_batch_size = VALUES(pull_batch_size),
                    status = VALUES(status),
                    metadata_json = VALUES(metadata_json),
                    id = LAST_INSERT_ID(id)
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
            row_id = cursor.lastrowid
        self._conn.commit()
        if row_id is None:
            raise RuntimeError("failed to upsert connector profile")
        return int(row_id)

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
            sql += " WHERE connector_system = %s"
            params.append(connector_system.value)
        sql += " ORDER BY connector_system, profile_name LIMIT %s"
        params.append(limit)

        with self._conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

        result: list[ConnectorProfile] = []
        for row in rows:
            result.append(
                ConnectorProfile(
                    connector_system=ConnectorSystem(row["connector_system"]),
                    profile_name=row["profile_name"],
                    base_url=row["base_url"],
                    auth_type=ConnectorAuthType(row["auth_type"]),
                    auth_config=self._decode_json(row["auth_config_json"]),
                    timeout_ms=int(row["timeout_ms"]),
                    pull_batch_size=int(row["pull_batch_size"]),
                    status=ConnectorProfileStatus(row["status"]),
                    metadata={k: v for k, v in self._decode_json(row["metadata_json"]).items() if k != "adapter_type"},
                    adapter_type=ConnectorAdapterType(
                        self._decode_json(row["metadata_json"]).get("adapter_type", "generic")
                    ),
                )
            )
        return result

    def get_connector_profile(self, connector_system: ConnectorSystem, profile_name: str) -> ConnectorProfile | None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT connector_system, profile_name, base_url, auth_type, auth_config_json,
                       timeout_ms, pull_batch_size, status, metadata_json
                FROM connector_profiles
                WHERE connector_system = %s AND profile_name = %s
                """,
                (connector_system.value, profile_name),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        metadata_raw = self._decode_json(row["metadata_json"])
        adapter_type = metadata_raw.get("adapter_type", "generic")
        sanitized_metadata = {k: v for k, v in metadata_raw.items() if k != "adapter_type"}
        return ConnectorProfile(
            connector_system=ConnectorSystem(row["connector_system"]),
            profile_name=row["profile_name"],
            base_url=row["base_url"],
            auth_type=ConnectorAuthType(row["auth_type"]),
            auth_config=self._decode_json(row["auth_config_json"]),
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
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_checkpoints (connector_system, profile_name, cursor, watermark)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `cursor` = VALUES(`cursor`),
                    watermark = VALUES(watermark),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (connector_system.value, profile_name, cursor, watermark),
            )
        self._conn.commit()

    def get_connector_checkpoint(self, connector_system: ConnectorSystem, profile_name: str) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT connector_system, profile_name, `cursor`, watermark, updated_at
                FROM connector_checkpoints
                WHERE connector_system = %s AND profile_name = %s
                """,
                (connector_system.value, profile_name),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "connector_system": row["connector_system"],
            "profile_name": row["profile_name"],
            "cursor": row["cursor"],
            "watermark": row["watermark"],
            "updated_at": str(row["updated_at"]),
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
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO connector_pull_runs (
                    connector_system, profile_name, mode, from_cursor, next_cursor,
                    pulled_count, accepted_count, replayed_count, sample_event_ids_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            row_id = cur.lastrowid
        self._conn.commit()
        if row_id is None:
            raise RuntimeError("failed to append connector pull run")
        return int(row_id)

    @staticmethod
    def _decode_json(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _row_to_sub_agent_task(row: Any) -> SubAgentTaskRecord:
        completed_at_raw = row["completed_at"]
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
            result_payload=TiDBControlPlaneStore._decode_json(row["result_payload_json"]),
            error=row["error"],
            worker_id=row["worker_id"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=str(completed_at_raw) if completed_at_raw is not None else None,
        )
