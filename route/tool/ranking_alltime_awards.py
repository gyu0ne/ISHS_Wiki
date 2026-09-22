"""Confirm captured all-time rank contributions after a 24-hour survival window."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Set
from contextlib import closing
from datetime import datetime

from .ranking_contribution_scores import ContributorEntry, HistoryRevision
from .ranking_contribution_state import as_kst
from .ranking_contributions import compute_contribution_scores
from .ranking_monthly_awards import Connection, record_alltime_rank


def ensure_alltime_schema(connection: Connection, sql: Callable[[str], str]) -> None:
    mysql = sql("?") == "%s"
    member_type = "VARCHAR(128) COLLATE utf8mb4_bin" if mysql else "TEXT"
    suffix = " CHARACTER SET utf8mb4" if mysql else ""
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS contributor_alltime_candidates (member_id "
            + member_type + " NOT NULL, rank_threshold INTEGER NOT NULL, "
            "reached_at BIGINT NOT NULL, revision_limits TEXT NOT NULL, "
            "cutoff_score VARCHAR(64) NOT NULL, cutoff_member " + member_type
            + " NOT NULL, PRIMARY KEY (member_id, rank_threshold))" + suffix
        )


def confirm_alltime_candidates(
    connection: Connection,
    sql: Callable[[str], str],
    entries: tuple[ContributorEntry, ...],
    revisions: tuple[HistoryRevision, ...],
    documents: Mapping[str, str],
    members: Set[str],
    now: datetime,
) -> None:
    """Confirm original contributions against frozen competitors, then seed new candidates."""
    now_epoch = int(as_kst(now).timestamp())
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            sql("SELECT member_id, CAST(rank_threshold AS CHAR), CAST(reached_at AS CHAR), "
                "revision_limits, cutoff_score, cutoff_member FROM contributor_alltime_candidates "
                "WHERE reached_at <= ?"),
            (now_epoch - 86400,),
        )
        retained_by_snapshot: dict[str, dict[str, float]] = {}
        for member, threshold, reached_at, serialized, cutoff_score, cutoff_member in cursor.fetchall():
            if serialized not in retained_by_snapshot:
                limits: dict[str, int] = json.loads(serialized)
                retained_by_snapshot[serialized] = {
                    entry.user_id: entry.score for entry in compute_contribution_scores(
                        revisions, documents, members, now, credit_limits=limits
                    ).contributors()
                }
            score = retained_by_snapshot[serialized].get(member, 0)
            cutoff = float(cutoff_score)
            if score > 0 and (score > cutoff or score == cutoff and member < cutoff_member):
                record_alltime_rank(connection, (member, int(threshold)), sql)
            cursor.execute(
                sql("DELETE FROM contributor_alltime_candidates WHERE member_id = ? "
                    "AND rank_threshold = ? AND reached_at = ? AND revision_limits = ?"),
                (member, int(threshold), int(reached_at), serialized),
            )
        cursor.execute("SELECT member_id, CAST(best_rank AS CHAR) FROM contributor_alltime_results")
        earned = {member: int(rank) for member, rank in cursor.fetchall()}
        limits = {}
        future_titles: set[str] = set()
        for revision in sorted(revisions, key=lambda row: (row.title, int(row.id))):
            if as_kst(revision.date) > as_kst(now):
                future_titles.add(revision.title)
            if revision.title not in future_titles:
                limits[revision.title] = int(revision.id)
        serialized = json.dumps(limits, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        conflict = (
            " ON DUPLICATE KEY UPDATE member_id = member_id"
            if sql("?") == "%s" else " ON CONFLICT(member_id, rank_threshold) DO NOTHING"
        )
        positive = tuple(entry for entry in entries if entry.score > 0)
        for rank, entry in enumerate(positive[:10], 1):
            competitors = tuple(other for other in positive if other.user_id != entry.user_id)
            for threshold in (1, 3, 10):
                if rank > threshold or earned.get(entry.user_id, 11) <= threshold:
                    continue
                competitor = competitors[threshold - 1] if len(competitors) >= threshold else None
                cursor.execute(
                    sql("INSERT INTO contributor_alltime_candidates "
                        "(member_id, rank_threshold, reached_at, revision_limits, cutoff_score, cutoff_member) "
                        "VALUES (?, ?, ?, ?, ?, ?)" + conflict),
                    (entry.user_id, threshold, now_epoch, serialized,
                     repr(competitor.score) if competitor else "0", competitor.user_id if competitor else ""),
                )
