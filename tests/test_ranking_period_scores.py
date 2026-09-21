from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ranking_package_support import bootstrap_route_tool_package


bootstrap_route_tool_package()

from route.tool.ranking_contributions import (
    HistoryRevision,
    compute_contribution_scores,
    compute_contributors,
)
from route.tool.ranking_contributor_cache import ContributorCache


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 4, 30, 0, 30, tzinfo=KST)


def revision(
    revision_id: int,
    title: str,
    data: str,
    day: datetime,
    author: str,
    *,
    mode: str = "",
) -> HistoryRevision:
    return HistoryRevision(
        id=str(revision_id),
        title=title,
        data=data,
        date=day,
        ip=author,
        send="",
        leng=len(data),
        hide="",
        type=mode,
    )


def scores(*revisions: HistoryRevision, current: dict[str, str]):
    return compute_contribution_scores(
        revisions,
        current,
        {"alice", "bob"},
        NOW,
    )


def test_adjacent_kst_calendar_months_are_separate_periods() -> None:
    # Given: mature contributions on opposite sides of a KST month boundary.
    history = (
        revision(1, "march", "m", datetime(2026, 3, 31, 23, 59, tzinfo=KST), "alice", mode="r1"),
        revision(1, "april", "a", datetime(2026, 4, 1, 0, 0, tzinfo=KST), "bob", mode="r1"),
    )

    # When: month scores are projected from the full replay.
    actual = scores(*history, current={"march": "m", "april": "a"})

    # Then: each contribution belongs only to its original KST calendar month.
    assert [entry.user_id for entry in actual.contributors("2026-03")] == ["alice"]
    assert [entry.user_id for entry in actual.contributors("2026-04")] == ["bob"]


def test_restore_keeps_original_addition_month() -> None:
    # Given: January content is deleted and restored in March.
    history = (
        revision(1, "A", "abc", datetime(2026, 1, 1, tzinfo=KST), "alice", mode="r1"),
        revision(2, "A", "", datetime(2026, 3, 20, tzinfo=KST), "bob", mode="delete"),
        revision(3, "A", "abc", datetime(2026, 3, 22, tzinfo=KST), "bob"),
    )

    # When: the same buckets are viewed as all-time and by calendar month.
    actual = scores(*history, current={"A": "abc"})

    # Then: restoration retains Alice's original January bucket.
    assert [entry.user_id for entry in actual.contributors("all")] == ["alice"]
    assert [entry.user_id for entry in actual.contributors("2026-01")] == ["alice"]
    assert actual.contributors("2026-03") == ()


def test_redeletion_keeps_first_deletion_month() -> None:
    # Given: Bob deletes content in February, it is restored, then deleted in March.
    history = (
        revision(1, "A", "abc", datetime(2025, 12, 1, tzinfo=KST), "alice", mode="r1"),
        revision(2, "A", "", datetime(2026, 2, 1, tzinfo=KST), "bob", mode="delete"),
        revision(3, "A", "abc", datetime(2026, 3, 20, tzinfo=KST), "alice"),
        revision(4, "A", "", datetime(2026, 3, 22, tzinfo=KST), "bob", mode="delete"),
    )

    # When: Bob's monthly scores are projected after the second deletion matures.
    actual = scores(*history, current={"A": ""})

    # Then: the removal stays in its first February month.
    assert [entry.user_id for entry in actual.contributors("all")] == ["bob"]
    assert [entry.user_id for entry in actual.contributors("2026-02")] == ["bob"]
    assert actual.contributors("2026-03") == ()


def test_contributor_total_is_sum_of_raw_document_scores() -> None:
    # Given: one author contributes on separate days to two documents.
    history = (
        revision(1, "A", "a" * 100, datetime(2026, 3, 10, tzinfo=KST), "alice", mode="r1"),
        revision(1, "B", "b" * 200, datetime(2026, 3, 11, tzinfo=KST), "alice", mode="r1"),
    )

    # When: contributor and per-document scores are read from one replay.
    actual = scores(*history, current={"A": "a" * 100, "B": "b" * 200})
    contributor = actual.contributors("all")[0]
    documents = actual.documents("alice", "all")

    # Then: raw document scores add exactly to the raw total and remain score sorted.
    assert contributor.score == sum(row.score for row in documents)
    assert [row.title for row in documents] == ["B", "A"]
    assert len(actual.buckets) == 2


def test_all_time_projection_preserves_existing_compute_contract() -> None:
    # Given: retained additions and a matured deletion across two documents.
    history = (
        revision(1, "A", "abc", datetime(2026, 1, 1, tzinfo=KST), "alice", mode="r1"),
        revision(1, "B", "xy", datetime(2026, 1, 2, tzinfo=KST), "alice", mode="r1"),
        revision(2, "B", "", datetime(2026, 2, 1, tzinfo=KST), "bob", mode="delete"),
    )
    current = {"A": "abc", "B": ""}

    # When: callers use either the legacy helper or the new full-history result.
    legacy = compute_contributors(history, current, {"alice", "bob"}, NOW)
    projected = scores(*history, current=current).contributors("all")

    # Then: the legacy return value is unchanged.
    assert legacy == projected


def test_document_cache_is_isolated_by_account_id_when_names_match(tmp_path: Path) -> None:
    # Given: two account IDs with the same display name and different documents.
    database = tmp_path / "cache.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            create table data (title text, data text);
            create table acl (title text, data text, type text);
            create table back (link text, type text);
            create table user_set (name text, id text);
            create table history (
                id text, title text, data text, date text, ip text,
                send text, leng text, hide text, type text
            );
            """
        )
        connection.executemany("insert into data values (?, ?)", (("A", "aaa"), ("B", "bb")))
        connection.executemany("insert into user_set values ('pw', ?)", (("member-1",), ("member-2",)))
        old = datetime(2026, 1, 1, tzinfo=KST).isoformat()
        connection.executemany(
            "insert into history values ('1', ?, ?, ?, ?, '', ?, '', 'r1')",
            (("A", "aaa", old, "member-1", "+3"), ("B", "bb", old, "member-2", "+2")),
        )

    @contextmanager
    def connect():
        with sqlite3.connect(database) as connection:
            yield connection

    cache = ContributorCache(connect, lambda sql: sql, lambda _connection, _member: "same", lambda: NOW.timestamp(), None)

    # When: one atomic refresh publishes rankings and account-owned documents.
    cache._refresh()

    # Then: same-name accounts receive only their own raw document score rows.
    first, generated_at, state = cache.document_snapshot("member-1")
    second, second_generated_at, second_state = cache.document_snapshot("member-2")
    assert [row["title"] for row in first] == ["A"]
    assert [row["title"] for row in second] == ["B"]
    assert (generated_at, state) == (second_generated_at, second_state) == (int(NOW.timestamp()), "ready")
    assert cache.snapshot("member-1", "2026-01")[0]
    assert cache.snapshot("member-1", "2025-12") == ((), int(NOW.timestamp()), "ready", None)
