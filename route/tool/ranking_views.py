"""Persistent, database-only realtime popularity ranking API."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from math import exp2
from typing import Final, Protocol

WINDOW_SECONDS: Final = 3600
RETENTION_SECONDS: Final = 86400
HALF_LIFE_SECONDS: Final = 900


class SqlTransform(Protocol):
    def __call__(self, statement: str) -> str: ...


class Cursor(Protocol):
    rowcount: int

    def close(self) -> None: ...

    def execute(self, statement: str, parameters: Sequence[str | int] = ()) -> None: ...

    def fetchall(self) -> list[tuple[str, str, int]]: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...


@dataclass(frozen=True, slots=True)
class PopularDocument:
    """One document eligible for the realtime popularity ranking."""

    title: str
    score: float
    readers: int
    last_view: int


def ensure_schema(conn: Connection, sql_transform: SqlTransform) -> None:
    """Create the portable table and its recent-view index when absent."""
    cursor = conn.cursor()
    try:
        if sql_transform('?') == '%s':
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS realtime_popularity_views ('
                'document_key CHAR(64) NOT NULL, title TEXT NOT NULL, '
                'member_token_hash CHAR(64) NOT NULL, viewed_at BIGINT NOT NULL, '
                'PRIMARY KEY (document_key, member_token_hash), '
                'KEY realtime_popularity_views_recent_idx (viewed_at)'
                ') CHARACTER SET utf8mb4'
            )
        else:
            cursor.execute(
                'CREATE TABLE IF NOT EXISTS realtime_popularity_views ('
                'document_key TEXT NOT NULL, title TEXT NOT NULL, '
                'member_token_hash TEXT NOT NULL, viewed_at INTEGER NOT NULL, '
                'PRIMARY KEY (document_key, member_token_hash)'
                ')'
            )
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS realtime_popularity_views_recent_idx '
                'ON realtime_popularity_views (viewed_at)'
            )
    finally:
        cursor.close()


def record_view(
    conn: Connection,
    document_id: str,
    title: str,
    member_token: str,
    now: int,
    sql_transform: SqlTransform,
) -> bool:
    """Persist one member's first qualified view in each sixty-minute window."""
    if not member_token:
        return False

    cursor = conn.cursor()
    try:
        cursor.execute(
            sql_transform('DELETE FROM realtime_popularity_views WHERE viewed_at < ?'),
            (now - RETENTION_SECONDS,),
        )
        document_key = _hash(document_id)
        member_hash = _hash(member_token)
        if sql_transform('?') == '%s':
            cursor.execute(
                sql_transform(
                    'INSERT INTO realtime_popularity_views '
                    '(document_key, title, member_token_hash, viewed_at) VALUES (?, ?, ?, ?) '
                    'ON DUPLICATE KEY UPDATE '
                    'title = IF(viewed_at <= VALUES(viewed_at) - ?, VALUES(title), title), '
                    'viewed_at = IF(viewed_at <= VALUES(viewed_at) - ?, VALUES(viewed_at), viewed_at)'
                ),
                (document_key, title, member_hash, now, WINDOW_SECONDS, WINDOW_SECONDS),
            )
        else:
            cursor.execute(
                sql_transform(
                    'INSERT INTO realtime_popularity_views '
                    '(document_key, title, member_token_hash, viewed_at) VALUES (?, ?, ?, ?) '
                    'ON CONFLICT(document_key, member_token_hash) DO UPDATE SET '
                    'title = excluded.title, viewed_at = excluded.viewed_at '
                    'WHERE viewed_at <= excluded.viewed_at - ?'
                ),
                (document_key, title, member_hash, now, WINDOW_SECONDS),
            )
        return cursor.rowcount > 0
    finally:
        cursor.close()


def get_popular(conn: Connection, now: int, sql_transform: SqlTransform) -> list[PopularDocument]:
    """Return qualifying documents ordered by score, recency, then title."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql_transform(
                'SELECT document_key, title, viewed_at FROM realtime_popularity_views '
                'WHERE viewed_at > ? AND viewed_at <= ? '
                'ORDER BY document_key, viewed_at, title'
            ),
            (now - WINDOW_SECONDS, now),
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()

    aggregates: dict[str, tuple[str, float, int, int]] = {}
    for document_key, title, viewed_at in rows:
        score = score_views((viewed_at,), now)
        current = aggregates.get(document_key)
        if current is None:
            aggregates[document_key] = (title, score, 1, viewed_at)
        else:
            current_title, current_score, readers, last_view = current
            preferred_title = title if viewed_at > last_view else min(title, current_title)
            aggregates[document_key] = (
                preferred_title,
                current_score + score,
                readers + 1,
                max(last_view, viewed_at),
            )

    return sorted(
        (
            PopularDocument(title, score, readers, last_view)
            for title, score, readers, last_view in aggregates.values()
            if readers >= 3
        ),
        key=lambda document: (-document.score, -document.last_view, document.title),
    )


def score_views(viewed_at: Sequence[int], now: int) -> float:
    """Pure half-life scorer for epoch-second view timestamps."""
    return sum(exp2(-(now - timestamp) / HALF_LIFE_SECONDS) for timestamp in viewed_at)


def _hash(value: str) -> str:
    return sha256(value.encode('utf-8')).hexdigest()
