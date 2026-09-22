"""Checkpoint tables and history triggers for SQLite and MySQL."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ranking_checkpoint_store import CheckpointConnection
    from .ranking_monthly_awards import Cursor


def _create_mysql_object(cursor: Cursor, statement: str, exists_code: int) -> None:
    """Tolerate only an identical object created by a concurrent initializer."""
    from pymysql.err import OperationalError

    try:
        cursor.execute(statement)
    except OperationalError as error:
        if error.args[0] != exists_code:
            raise


def ensure_schema(connection: CheckpointConnection, sql: Callable[[str], str]) -> None:
    """Install tracking before the first read; never replace live triggers."""
    cursor = connection.cursor()
    try:
        mysql = sql("?") == "%s"
        suffix = (
            " ENGINE=InnoDB CHARACTER SET utf8mb4 COLLATE utf8mb4_bin" if mysql else ""
        )
        payload_type = "LONGTEXT" if mysql else "TEXT"
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_checkpoint_state (singleton INTEGER PRIMARY KEY, generation BIGINT NOT NULL, dirty_seq BIGINT NOT NULL, processed_seq BIGINT NOT NULL, member_hash VARCHAR(64) NOT NULL, version INTEGER NOT NULL)"
            + suffix
        )
        insert = "INSERT IGNORE" if mysql else "INSERT OR IGNORE"
        cursor.execute(
            insert + " INTO contributor_checkpoint_state VALUES (1, 0, 0, 0, '', 1)"
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_checkpoints (title_key CHAR(64) PRIMARY KEY, title TEXT NOT NULL, metadata "
            + payload_type
            + " NOT NULL, payload "
            + payload_type
            + " NOT NULL)"
            + suffix
        )
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_history_changes (seq BIGINT NOT NULL, title TEXT NOT NULL, revision_id TEXT NOT NULL, kind VARCHAR(8) NOT NULL)"
            + suffix
        )
        if mysql:
            cursor.execute(
                "SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'contributor_history_changes' AND INDEX_NAME = 'contributor_history_changes_seq'"
            )
            if not cursor.fetchall():
                _create_mysql_object(
                    cursor,
                    "CREATE INDEX contributor_history_changes_seq ON contributor_history_changes (seq)",
                    1061,
                )
            cursor.execute(
                "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()"
            )
            existing = {row[0] for row in cursor.fetchall()}
        else:
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS contributor_history_changes_seq ON contributor_history_changes (seq)"
            )
            existing = set()
        for operation, references, kind in (
            ("INSERT", ("NEW",), "append"),
            ("UPDATE", ("OLD", "NEW"), "rebuild"),
            ("DELETE", ("OLD",), "rebuild"),
        ):
            name = "contributor_history_" + operation.lower()
            if name in existing:
                continue
            body = "UPDATE contributor_checkpoint_state SET dirty_seq = dirty_seq + 1 WHERE singleton = 1; "
            for reference in references:
                body += (
                    "INSERT INTO contributor_history_changes (seq, title, revision_id, kind) "
                    f"SELECT dirty_seq, {reference}.title, {reference}.id, '{kind}' FROM contributor_checkpoint_state WHERE singleton = 1; "
                )
            guard = "" if mysql else "IF NOT EXISTS "
            statement = f"CREATE TRIGGER {guard}{name} AFTER {operation} ON history FOR EACH ROW BEGIN {body} END"
            if mysql:
                _create_mysql_object(cursor, statement, 1359)
            else:
                cursor.execute(statement)
        connection.commit()
    finally:
        cursor.close()
