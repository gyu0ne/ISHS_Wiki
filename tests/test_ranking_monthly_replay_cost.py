from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Set
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_contribution_engine import DocumentContributionEngine
from route.tool.ranking_contribution_scores import HistoryRevision
from route.tool.ranking_contribution_state import as_kst
from route.tool.ranking_contributions import compute_contribution_scores
from route.tool.ranking_monthly_awards import MonthlyHistory, ensure_schema, finalize_months


def revision(number: int, month: int, *, title: str = "Page") -> HistoryRevision:
    return HistoryRevision(str(number), title, "a" * number, datetime(2026, month, 10),
                           "alice" if number % 2 else "bob", "", number, "", "")


def sql(statement: str) -> str:
    return statement


def test_each_revision_is_processed_once_during_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: two documents grow across six unfinalized months.
    rows = tuple(revision(month, month, title=title)
                 for title in ("Page", "Other") for month in range(1, 7))
    members = frozenset({"alice", "bob"})
    history = MonthlyHistory(rows, members, members, datetime(2026, 7, 2))
    processed: list[tuple[str, str]] = []
    original = DocumentContributionEngine.advance

    def counted(engine: DocumentContributionEngine, revisions: Iterable[HistoryRevision],
                member_ids: Set[str], now: datetime) -> None:
        batch = tuple(revisions)
        processed.extend((row.title, row.id) for row in batch)
        original(engine, batch, member_ids, now)

    monkeypatch.setattr(DocumentContributionEngine, "advance", counted)
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: all six months are finalized together.
        finalize_months(connection, sql, history)
        # Then: revision diff work grows with history, not months times history.
        assert len(processed) == len(rows)
        assert len(set(processed)) == len(rows)


@pytest.mark.parametrize("edge", ["plain", "future", "pending", "hidden", "gap", "maturity"])
def test_incremental_backfill_matches_legacy_cutoffs(edge: str) -> None:
    # Given: a historical edge case plus a competing document and an ineligible member.
    rows = [revision(month, month) for month in range(1, 5)]
    if edge == "future":
        rows[1] = replace(rows[1], date=datetime(2026, 3, 10))
        rows[2] = replace(rows[2], date=datetime(2026, 1, 11), data="zzzz")
    if edge == "pending":
        rows[1] = replace(rows[1], type="edit_request", leng=0, data="unaccepted")
    if edge == "hidden":
        rows[1] = replace(rows[1], hide="O")
    if edge == "gap":
        rows = [rows[0], rows[2], rows[3]]
    if edge == "maturity":
        rows[0] = replace(rows[0], date=datetime(2026, 1, 31, 23, 59, 59))
        rows[1] = replace(rows[1], date=datetime(2026, 2, 1, 1), data="")
    rows.extend([revision(1, 1, title="Other"),
                 replace(revision(2, 2, title="Other"), ip="123", data="z" * 50)])
    members = frozenset({"alice", "bob", "123"})
    history = MonthlyHistory(tuple(reversed(rows)), members, frozenset({"alice", "bob"}),
                             datetime(2026, 5, 2))
    expected = []
    for month in range(1, 5):
        cutoff = as_kst(datetime(2026, month + 1, 1) + timedelta(days=1))
        blocked: set[str] = set()
        replay = []
        for row in sorted(rows, key=lambda row: (row.title, int(row.id))):
            if as_kst(row.date) > cutoff:
                blocked.add(row.title)
            if row.title not in blocked:
                replay.append(row)
        documents = {row.title: row.data for row in replay
                     if not (row.type == "edit_request" and row.leng == 0)}
        scores = compute_contribution_scores(replay, documents, members, cutoff, require_mature=True)
        period = f"2026-{month:02}"
        winners = [entry.user_id for entry in scores.contributors(period)
                   if entry.score > 0 and entry.user_id in history.eligible_members][:10]
        expected.append((period, json.dumps(winners, ensure_ascii=False)))
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: the replacement replay finalizes the same historical cutoffs.
        finalize_months(connection, sql, history)
        # Then: all persisted ranks match the independent legacy replay.
        assert connection.execute(
            "SELECT period, winners FROM contributor_monthly_results ORDER BY period"
        ).fetchall() == expected
