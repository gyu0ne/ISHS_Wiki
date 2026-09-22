"""Immutable monthly competition results, replayed at the 24-hour cutoff."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Protocol

from .ranking_contribution_scores import HistoryRevision
from .ranking_contribution_state import as_kst
from .ranking_contributions import compute_contribution_scores


class Cursor(Protocol):
    def execute(self, statement: str, parameters: Sequence[str | int] = ()) -> None: ...
    def fetchall(self) -> list[tuple[str, ...]]: ...
    def close(self) -> None: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...


@dataclass(frozen=True, slots=True)
class MonthlyAwards:
    best_rank: int | None = None
    wins: int = 0
    alltime_best_rank: int | None = None


@dataclass(frozen=True, slots=True)
class MonthlyHistory:
    revisions: tuple[HistoryRevision, ...]
    members: frozenset[str]
    eligible_members: frozenset[str]
    now: datetime


def ensure_schema(connection: Connection, sql: Callable[[str], str]) -> None:
    cursor = connection.cursor()
    try:
        suffix = " CHARACTER SET utf8mb4" if sql("?") == "%s" else ""
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_monthly_results ("
            "period CHAR(7) NOT NULL PRIMARY KEY, winners TEXT NOT NULL)" + suffix
        )
        member_type = "VARCHAR(128) COLLATE utf8mb4_bin" if suffix else "TEXT"
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_alltime_results ("
            "member_id " + member_type + " NOT NULL PRIMARY KEY, best_rank INTEGER NOT NULL)" + suffix
        )
    finally:
        cursor.close()


def get_member_awards(
    connection: Connection, member_id: str, sql: Callable[[str], str]
) -> MonthlyAwards:
    """Read finalized competition ranks without exposing other account IDs."""
    cursor = connection.cursor()
    try:
        cursor.execute(sql("SELECT winners FROM contributor_monthly_results"))
        ranks = []
        for (serialized,) in cursor.fetchall():
            winners: list[str] = json.loads(serialized)
            if member_id in winners:
                ranks.append(winners.index(member_id) + 1)
        cursor.execute(
            sql("SELECT CAST(best_rank AS CHAR) FROM contributor_alltime_results WHERE member_id = ?"),
            (member_id,),
        )
        alltime = cursor.fetchall()
        return MonthlyAwards(
            min(ranks) if ranks else None, ranks.count(1), int(alltime[0][0]) if alltime else None
        )
    finally:
        cursor.close()


def record_alltime_rank(
    connection: Connection, member_rank: tuple[str, int], sql: Callable[[str], str]
) -> None:
    """Retain each observed member's best positive top-ten rank across refreshes."""
    member_id, rank = member_rank
    if not 1 <= rank <= 10:
        return
    cursor = connection.cursor()
    try:
        conflict = (
            " ON DUPLICATE KEY UPDATE best_rank = LEAST(best_rank, VALUES(best_rank))"
            if sql("?") == "%s"
            else " ON CONFLICT(member_id) DO UPDATE SET best_rank = MIN(best_rank, excluded.best_rank)"
        )
        cursor.execute(
            sql("INSERT INTO contributor_alltime_results (member_id, best_rank) VALUES (?, ?)" + conflict),
            (member_id, rank),
        )
    finally:
        cursor.close()


def _next_month(month: datetime) -> datetime:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def _replay(history: MonthlyHistory, cutoff: datetime) -> tuple[HistoryRevision, ...]:
    """Clip each document at the first future revision, including backdated successors."""
    blocked: set[str] = set()
    replay: list[HistoryRevision] = []
    for revision in sorted(history.revisions, key=lambda item: (item.title, int(item.id))):
        if as_kst(revision.date) > cutoff:
            blocked.add(revision.title)
        if revision.title not in blocked:
            replay.append(revision)
    return tuple(replay)


def finalize_months(
    connection: Connection, sql: Callable[[str], str], history: MonthlyHistory
) -> None:
    """Atomically insert each complete month once; failures never mark it complete."""
    if not history.revisions:
        return
    now = as_kst(history.now)
    elapsed_dates = [as_kst(row.date) for row in history.revisions if as_kst(row.date) <= now]
    if not elapsed_dates:
        return
    month = min(elapsed_dates).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    cursor = connection.cursor()
    try:
        cursor.execute(sql("SELECT period FROM contributor_monthly_results"))
        complete = {row[0] for row in cursor.fetchall()}
        while _next_month(month) + timedelta(days=1) <= now:
            period = month.strftime("%Y-%m")
            cutoff = _next_month(month) + timedelta(days=1)
            if period not in complete:
                replay = _replay(history, cutoff)
                documents = {
                    row.title: row.data for row in replay
                    if not (row.type == "edit_request" and row.leng == 0)
                }
                scores = compute_contribution_scores(replay, documents, history.members, cutoff)
                winners = [
                    entry.user_id for entry in scores.contributors(period)
                    if entry.score > 0 and entry.user_id in history.eligible_members
                ][:10]
                conflict = (
                    " ON DUPLICATE KEY UPDATE period = VALUES(period)"
                    if sql("?") == "%s" else " ON CONFLICT(period) DO NOTHING"
                )
                cursor.execute(
                    sql("INSERT INTO contributor_monthly_results (period, winners) VALUES (?, ?)" + conflict),
                    (period, json.dumps(winners, ensure_ascii=False)),
                )
            month = _next_month(month)
    finally:
        cursor.close()
