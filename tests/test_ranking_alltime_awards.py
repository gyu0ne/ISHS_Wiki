from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_alltime_awards import confirm_alltime_candidates, ensure_alltime_schema
from route.tool.ranking_contribution_scores import HistoryRevision
from route.tool.ranking_contributions import compute_contributors
from route.tool.ranking_monthly_awards import ensure_schema, get_member_awards

START = datetime.fromisoformat("2026-01-01T00:00:00+09:00")
MEMBERS = frozenset({"alice", "bob"})


def sql(statement: str) -> str:
    return statement


def revision(member: str, body: str, number: int = 1, hours: int = 0) -> HistoryRevision:
    return HistoryRevision(str(number), member, body, START + timedelta(hours=hours), member, "", len(body), "", "")


def refresh(connection: sqlite3.Connection, revisions: tuple[HistoryRevision, ...], seconds: int) -> None:
    documents = {row.title: row.data for row in revisions}
    now = START + timedelta(seconds=seconds)
    entries = compute_contributors(revisions, documents, MEMBERS, now)
    confirm_alltime_candidates(connection, sql, entries, revisions, documents, MEMBERS, now)


def setup(connection: sqlite3.Connection) -> None:
    ensure_schema(connection, sql)
    ensure_alltime_schema(connection, sql)


@pytest.mark.parametrize("seconds,expected", [(0, None), (86399, None), (86400, 1)])
def test_candidate_confirms_at_exact_day(seconds: int, expected: int | None) -> None:
    # Given: Alice has a live first-place contribution candidate.
    rows = (revision("alice", "a" * 100),)
    with closing(sqlite3.connect(":memory:")) as connection:
        setup(connection)
        refresh(connection, rows, 0)
        # When: the survival window reaches its boundary.
        refresh(connection, rows, seconds)
        # Then: no achievement exists before a full day.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == expected


def test_overtaken_candidate_uses_frozen_competitor_score() -> None:
    # Given: Alice leads Bob when her contribution is captured.
    rows = (revision("alice", "a" * 100), revision("bob", "b" * 50))
    with closing(sqlite3.connect(":memory:")) as connection:
        setup(connection)
        refresh(connection, rows, 0)
        # When: Bob overtakes her while Alice's original contribution survives.
        refresh(connection, (*rows, revision("bob", "b" * 1000, 2, 1)), 86400)
        # Then: the frozen first-place candidate still qualifies.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 1


def test_new_contributions_do_not_replace_withdrawn_candidate() -> None:
    # Given: Alice reaches first with an original contribution.
    rows = (revision("alice", "a" * 100), revision("bob", "b" * 50))
    with closing(sqlite3.connect(":memory:")) as connection:
        setup(connection)
        refresh(connection, rows, 0)
        # When: she replaces all original content with a larger, later contribution.
        refresh(connection, (*rows, revision("alice", "z" * 1000, 2, 1)), 86400)
        # Then: the replacement does not satisfy the original survival window.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank is None


def test_raw_score_ties_use_member_order() -> None:
    # Given: equal raw scores are ordered by member ID.
    rows = (revision("alice", "x" * 100), revision("bob", "x" * 100))
    with closing(sqlite3.connect(":memory:")) as connection:
        setup(connection)
        refresh(connection, rows, 0)
        # When: both captured contributions survive a full day.
        refresh(connection, rows, 86400)
        # Then: the first threshold belongs to Alice; Bob earns the top-three threshold.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 1
        assert get_member_awards(connection, "bob", sql).alltime_best_rank == 3


def test_restart_and_duplicate_workers_keep_original_snapshot(tmp_path: Path) -> None:
    # Given: a candidate is persisted before the process stops.
    database = tmp_path / "candidates.sqlite3"
    rows = (revision("alice", "a" * 100),)
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        setup(connection)
        refresh(connection, rows, 0)

    def worker() -> None:
        with closing(sqlite3.connect(database, isolation_level=None)) as connection:
            refresh(connection, rows, 86399)

    # When: independent workers revisit the candidate before a restarted worker confirms it.
    with ThreadPoolExecutor(max_workers=2) as workers:
        for future in [workers.submit(worker) for _ in range(2)]:
            future.result()
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        assert get_member_awards(connection, "alice", sql).alltime_best_rank is None
        refresh(connection, rows, 86400)
        refresh(connection, rows, 86400)
        # Then: the immutable original timestamp leads to one durable award.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 1
        assert connection.execute("SELECT COUNT(*) FROM contributor_alltime_results").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM contributor_alltime_candidates").fetchone() == (0,)
