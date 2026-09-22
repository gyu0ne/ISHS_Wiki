from __future__ import annotations

import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()
from route.tool.ranking_contribution_scores import HistoryRevision
from route.tool.ranking_contribution_state import KST
from route.tool.ranking_monthly_awards import (
    MonthlyAwards, MonthlyHistory, ensure_schema, finalize_months, get_member_awards,
)


def revision(number: int, body: str, timestamp: str, author: str = "alice") -> HistoryRevision:
    return HistoryRevision(str(number), "Page", body, datetime.fromisoformat(timestamp), author, "", len(body), "", "")


def sql(statement: str) -> str:
    return statement


def history(*revisions: HistoryRevision, now: str = "2026-03-02T00:00:00+09:00") -> MonthlyHistory:
    return MonthlyHistory(tuple(revisions), frozenset({"alice", "bob", "123"}), frozenset({"alice", "bob"}), datetime.fromisoformat(now))


@pytest.mark.parametrize("now,expected", [
    ("2026-02-01T23:59:59+09:00", MonthlyAwards()),
    ("2026-02-02T00:00:00+09:00", MonthlyAwards(1, 1)),
])
def test_month_end_edit_waits_for_full_survival_window(now: str, expected: MonthlyAwards) -> None:
    # Given: a member adds content in the final second of January.
    data = history(revision(1, "a" * 100, "2026-01-31T23:59:59+09:00"), now=now)
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: the background refresh finalizes eligible months.
        finalize_months(connection, sql, data)
        # Then: only the full next-day cutoff awards January.
        assert get_member_awards(connection, "alice", sql) == expected


def test_backfill_replays_old_body_and_counts_distinct_winning_months() -> None:
    # Given: Alice wins January and February; March later replaces her entire document.
    data = history(
        revision(1, "a" * 100, "2026-01-10T00:00:00+09:00"),
        revision(2, "a" * 100 + "b" * 100, "2026-02-10T00:00:00+09:00"),
        revision(3, "c" * 100, "2026-03-10T00:00:00+09:00", "bob"),
        now="2026-03-20T00:00:00+09:00",
    )
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: the process refreshes twice, including a repeated historical replay.
        finalize_months(connection, sql, data)
        finalize_months(connection, sql, data)
        # Then: two distinct wins survive later edits and March remains open.
        assert get_member_awards(connection, "alice", sql) == MonthlyAwards(1, 2)
        assert get_member_awards(connection, "bob", sql) == MonthlyAwards()
        assert connection.execute("select period from contributor_monthly_results order by period").fetchall() == [("2026-01",), ("2026-02",)]


def test_ineligible_editors_do_not_displace_members_and_empty_month_is_final() -> None:
    # Given: anonymous and undisplayable accounts add more than the eligible member.
    data = history(
        revision(1, "x" * 1000, "2026-01-10T00:00:00+09:00", "anon"),
        revision(2, "x" * 1000 + "y" * 1000, "2026-01-11T00:00:00+09:00", "123"),
        revision(3, "x" * 1000 + "y" * 1000 + "a", "2026-01-12T00:00:00+09:00"),
    )
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: January and the following empty February finalize.
        finalize_months(connection, sql, data)
        # Then: Alice gets first once; February has a persisted empty result.
        assert get_member_awards(connection, "alice", sql) == MonthlyAwards(1, 1)
        assert get_member_awards(connection, "123", sql) == MonthlyAwards()
        assert connection.execute("select winners from contributor_monthly_results where period='2026-02'").fetchone() == ("[]",)


def test_finalized_result_is_immutable_after_eligibility_changes() -> None:
    # Given: January already awarded Alice.
    original = history(revision(1, "a", "2026-01-10T00:00:00+09:00"))
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        finalize_months(connection, sql, original)
        # When: a later refresh has no eligible members.
        changed = MonthlyHistory(original.revisions, original.members, frozenset(), original.now)
        finalize_months(connection, sql, changed)
        # Then: previously earned wins are retained.
        assert get_member_awards(connection, "alice", sql) == MonthlyAwards(1, 1)


def test_backdated_successor_cannot_cross_a_future_revision() -> None:
    # Given: revision 2 is in March but revision 3 carries a backdated January timestamp.
    data = history(
        revision(1, "a", "2026-01-10T00:00:00+09:00"),
        revision(2, "ab", "2026-03-10T00:00:00+09:00", "bob"),
        revision(3, "cccc", "2026-01-11T00:00:00+09:00", "bob"),
    )
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: January is replayed at its historical cutoff.
        finalize_months(connection, sql, data)
        # Then: future revision causality prevents Bob from winning the past month.
        assert get_member_awards(connection, "alice", sql) == MonthlyAwards(1, 1)
        assert get_member_awards(connection, "bob", sql) == MonthlyAwards()


def test_future_only_history_does_not_finalize_or_overflow() -> None:
    # Given: imported history includes a future timestamp outside today's competition.
    data = history(revision(1, "a", "9999-12-31T00:00:00+09:00"))
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: monthly finalization runs.
        finalize_months(connection, sql, data)
        # Then: future history produces no complete month or award.
        assert connection.execute("select count(*) from contributor_monthly_results").fetchone() == (0,)


def test_scoring_failure_never_inserts_a_completed_month() -> None:
    # Given: an invalid imported revision ID causes replay scoring to fail.
    malformed = HistoryRevision("bad", "Page", "a", datetime(2026, 1, 1, tzinfo=KST), "alice", "", 1, "", "")
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: finalization fails before obtaining a valid ranking.
        with pytest.raises(ValueError):
            finalize_months(connection, sql, history(malformed))
        # Then: it can retry later because no completion row was written.
        assert connection.execute("select count(*) from contributor_monthly_results").fetchone() == (0,)


def test_only_top_ten_members_receive_rank_awards() -> None:
    # Given: twelve members contribute decreasing quantities to different documents.
    members = frozenset(f"member-{number:02}" for number in range(12))
    revisions = tuple(
        HistoryRevision("1", member, "a" * (12 - number), datetime(2026, 1, 1, tzinfo=KST), member, "", 12 - number, "", "")
        for number, member in enumerate(sorted(members))
    )
    data = MonthlyHistory(revisions, members, members, datetime(2026, 2, 2, tzinfo=KST))
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: January finalizes.
        finalize_months(connection, sql, data)
        # Then: exact first, third and tenth places qualify; eleventh does not.
        assert get_member_awards(connection, "member-00", sql) == MonthlyAwards(1, 1)
        assert get_member_awards(connection, "member-02", sql) == MonthlyAwards(3, 0)
        assert get_member_awards(connection, "member-09", sql) == MonthlyAwards(10, 0)
        assert get_member_awards(connection, "member-10", sql) == MonthlyAwards()


def test_independent_workers_and_restart_cannot_duplicate_wins(tmp_path: Path) -> None:
    # Given: two worker connections target the same persisted monthly table.
    database = tmp_path / "monthly.sqlite3"
    data = history(revision(1, "a", "2026-01-10T00:00:00+09:00"))
    with closing(sqlite3.connect(database, isolation_level=None)) as connection:
        ensure_schema(connection, sql)

    def refresh() -> None:
        with closing(sqlite3.connect(database, isolation_level=None)) as connection:
            finalize_months(connection, sql, data)

    # When: independent workers overlap and a fresh connection refreshes again.
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(refresh) for _ in range(2)]
        for future in futures:
            future.result()
    refresh()
    # Then: the durable monthly primary key keeps exactly one win.
    with closing(sqlite3.connect(database)) as connection:
        assert get_member_awards(connection, "alice", sql) == MonthlyAwards(1, 1)


def test_alltime_best_rank_improves_but_survives_later_rank_falls() -> None:
    # Given: a member reaches tenth, then third, then first in separate refreshes.
    from route.tool import ranking_monthly_awards as awards
    with closing(sqlite3.connect(":memory:")) as connection:
        ensure_schema(connection, sql)
        # When: live observations improve and eventually fall again.
        awards.record_alltime_rank(connection, ("alice", 10), sql)
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 10
        awards.record_alltime_rank(connection, ("alice", 3), sql)
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 3
        awards.record_alltime_rank(connection, ("alice", 1), sql)
        awards.record_alltime_rank(connection, ("alice", 1), sql)
        awards.record_alltime_rank(connection, ("alice", 10), sql)
        awards.record_alltime_rank(connection, ("bob", 11), sql)
        # Then: the best observation persists once; eleventh place earns nothing.
        assert get_member_awards(connection, "alice", sql).alltime_best_rank == 1
        assert get_member_awards(connection, "bob", sql).alltime_best_rank is None
        assert connection.execute("select count(*) from contributor_alltime_results").fetchone() == (1,)


def test_cache_records_only_displayable_alltime_members(tmp_path: Path) -> None:
    # Given: a numeric fallback account has the most points, followed by two named accounts.
    from test_document_contributor_cache import build_cache
    # When: the real cache refreshes the existing historical ranking fixture.
    cache = build_cache(tmp_path)
    # Then: displayed members receive their actual ranks; numeric fallback receives none.
    with cache.connect() as connection:
        assert get_member_awards(connection, "member-a", sql).alltime_best_rank == 1
        assert get_member_awards(connection, "member-b", sql).alltime_best_rank == 2
        assert get_member_awards(connection, "123", sql).alltime_best_rank is None


def test_empty_cache_does_not_record_an_alltime_winner(tmp_path: Path) -> None:
    # Given: the normal cache database exists but has no score-eligible revisions.
    from test_document_contributor_cache import build_cache
    cache = build_cache(tmp_path)
    with cache.connect() as connection:
        connection.execute("delete from history")
        connection.execute("delete from data")
        connection.execute("delete from contributor_alltime_results")
    # When: the live cache refreshes the empty ranking.
    cache._refresh()
    # Then: no all-time achievement is awarded.
    with cache.connect() as connection:
        assert connection.execute("select count(*) from contributor_alltime_results").fetchone() == (0,)
