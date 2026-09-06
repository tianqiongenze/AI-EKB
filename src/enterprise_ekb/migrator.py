from __future__ import annotations

from pathlib import Path


class TiDBMigrator:
    def __init__(self, connection, migrations_dir: str) -> None:
        self._conn = connection
        self._migrations_dir = Path(migrations_dir)

    def migrate(self) -> list[str]:
        self._ensure_schema_migrations_table()
        applied = self._applied_versions()
        executed: list[str] = []

        for migration_file in sorted(self._migrations_dir.glob("*.sql")):
            version = migration_file.stem
            if version in applied:
                continue

            sql = migration_file.read_text(encoding="utf-8")
            statements = [segment.strip() for segment in sql.split(";") if segment.strip()]
            with self._conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            self._conn.commit()
            executed.append(version)

        return executed

    def _ensure_schema_migrations_table(self) -> None:
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        self._conn.commit()

    def _applied_versions(self) -> set[str]:
        with self._conn.cursor() as cursor:
            cursor.execute("SELECT version FROM schema_migrations")
            rows = cursor.fetchall()
        return {str(row[0] if isinstance(row, tuple) else row["version"]) for row in rows}
