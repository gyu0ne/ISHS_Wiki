"""Durable replay checkpoints and transactional history invalidation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from .ranking_monthly_awards import Connection


class CheckpointConnection(Connection, Protocol):
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(frozen=True, slots=True)
class CheckpointWrite:
    title: str
    metadata: str
    payload: str


@dataclass(frozen=True, slots=True)
class HistoryChange:
    seq: int
    title: str
    revision_id: str
    kind: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    generation: int
    watermark: int
    processed_seq: int
    member_hash: str
    version: int
    checkpoints: Mapping[str, str]
    events: tuple[HistoryChange, ...]


def ensure_schema(connection: CheckpointConnection, sql: Callable[[str], str]) -> None:
    from .ranking_checkpoint_schema import ensure_schema as create_schema

    create_schema(connection, sql)


def snapshot(connection: CheckpointConnection, sql: Callable[[str], str]) -> Snapshot:
    """Read lightweight state inside the caller's source-read transaction."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT generation, dirty_seq, processed_seq, member_hash, version FROM contributor_checkpoint_state WHERE singleton = 1"
        )
        generation, watermark, processed, members, version = cursor.fetchall()[0]
        cursor.execute("SELECT title, metadata FROM contributor_checkpoints")
        checkpoints = {title: metadata for title, metadata in cursor.fetchall()}
        cursor.execute(
            sql(
                "SELECT seq, title, revision_id, kind FROM contributor_history_changes WHERE seq > ? AND seq <= ? ORDER BY seq"
            ),
            (int(processed), int(watermark)),
        )
        events = tuple(
            HistoryChange(int(seq), title, revision, kind)
            for seq, title, revision, kind in cursor.fetchall()
        )
        return Snapshot(
            int(generation),
            int(watermark),
            int(processed),
            members,
            int(version),
            checkpoints,
            events,
        )
    finally:
        cursor.close()


def load_checkpoint(
    connection: CheckpointConnection, sql: Callable[[str], str], title: str
) -> str | None:
    """Read heavy replay state only for documents that need work."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            sql("SELECT payload FROM contributor_checkpoints WHERE title_key = ?"),
            (sha256(title.encode()).hexdigest(),),
        )
        rows = cursor.fetchall()
        return rows[0][0] if rows else None
    finally:
        cursor.close()


def publish(
    connection: CheckpointConnection,
    sql: Callable[[str], str],
    captured: Snapshot,
    updates: Sequence[CheckpointWrite],
    removals: Sequence[str],
    member_hash: str,
) -> bool:
    """Atomically advance a generation, retaining mutations after its watermark."""
    cursor = connection.cursor()
    committed = False
    started = False
    try:
        mysql = sql("?") == "%s"
        cursor.execute("START TRANSACTION" if mysql else "BEGIN IMMEDIATE")
        started = True
        lock = " FOR UPDATE" if mysql else ""
        cursor.execute(
            "SELECT generation FROM contributor_checkpoint_state WHERE singleton = 1"
            + lock
        )
        if int(cursor.fetchall()[0][0]) != captured.generation:
            return False
        for title in removals:
            cursor.execute(
                sql("DELETE FROM contributor_checkpoints WHERE title_key = ?"),
                (sha256(title.encode()).hexdigest(),),
            )
        conflict = (
            " ON DUPLICATE KEY UPDATE title = VALUES(title), metadata = VALUES(metadata), payload = VALUES(payload)"
            if mysql
            else " ON CONFLICT(title_key) DO UPDATE SET title = excluded.title, metadata = excluded.metadata, payload = excluded.payload"
        )
        for item in updates:
            cursor.execute(
                sql(
                    "INSERT INTO contributor_checkpoints (title_key, title, metadata, payload) VALUES (?, ?, ?, ?)"
                    + conflict
                ),
                (
                    sha256(item.title.encode()).hexdigest(),
                    item.title,
                    item.metadata,
                    item.payload,
                ),
            )
        cursor.execute(
            sql(
                "UPDATE contributor_checkpoint_state SET generation = generation + 1, processed_seq = ?, member_hash = ? WHERE singleton = 1"
            ),
            (captured.watermark, member_hash),
        )
        cursor.execute(
            sql("DELETE FROM contributor_history_changes WHERE seq <= ?"),
            (captured.watermark,),
        )
        cursor.execute("COMMIT")
        committed = True
        return True
    finally:
        try:
            if started and not committed:
                cursor.execute("ROLLBACK")
        finally:
            cursor.close()
