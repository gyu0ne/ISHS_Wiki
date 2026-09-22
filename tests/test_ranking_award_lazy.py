from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_alltime_awards import confirm_alltime_candidates, ensure_alltime_schema
from route.tool.ranking_contribution_scores import HistoryRevision
from route.tool.ranking_contributions import compute_contributors
from route.tool.ranking_monthly_awards import (
    MonthlyHistory, ensure_schema, finalize_months, get_member_awards,
)

START = datetime.fromisoformat("2026-01-10T00:00:00+09:00")
MEMBERS = frozenset({"alice"})
ROWS = (HistoryRevision("1", "Page", "abc", START, "alice", "", 3, "", ""),)


def sql(statement: str) -> str:
    return statement


@pytest.mark.parametrize("complete", [False, True])
def test_monthly_history_is_read_only_for_unfinished_months(complete: bool) -> None:
    # Given: January either still needs replay or was finalized previously.
    calls = []

    def load() -> tuple[HistoryRevision, ...]:
        calls.append(1)
        return ROWS

    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        if complete:
            connection.execute("INSERT INTO contributor_monthly_results VALUES ('2026-01', '[\"alice\"]')")
        now = datetime.fromisoformat("2026-02-02T00:00:00+09:00")
        # When: the refresh receives only persistent metadata and a lazy loader.
        finalize_months(connection, sql, MonthlyHistory((), MEMBERS, MEMBERS, now),
                        first_revision_at=START, load_revisions=load)
        # Then: the same award is available without rereading completed history.
        assert get_member_awards(connection, "alice", sql).wins == 1
        assert len(calls) == (0 if complete else 1)


@pytest.mark.parametrize("hours", [0, 23, 24])
def test_alltime_history_loads_only_when_candidate_is_due(hours: int) -> None:
    # Given: a captured first-place contribution, with metadata for seeding.
    calls = []

    def load() -> tuple[HistoryRevision, ...]:
        calls.append(1)
        return ROWS

    documents = {"Page": "abc"}
    entries = compute_contributors(ROWS, documents, MEMBERS, START)
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        ensure_alltime_schema(connection, sql)
        confirm_alltime_candidates(connection, sql, entries, (), documents, MEMBERS, START,
                                   load_revisions=load, revision_limits={"Page": 1})
        # When: a metadata-only refresh reaches the candidate's deadline.
        confirm_alltime_candidates(connection, sql, entries, (), documents, MEMBERS,
                                   START + timedelta(hours=hours),
                                   load_revisions=load, revision_limits={"Page": 1})
        # Then: only due candidates fetch history, still awarding the original rank.
        assert len(calls) == (1 if hours == 24 else 0)
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == (1 if hours == 24 else None)
