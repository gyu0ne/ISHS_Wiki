from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ranking_package_support import bootstrap_route_tool_package


bootstrap_route_tool_package()

from route.tool.ranking_contributor_cache import ContributorCache


NOW = datetime(2026, 4, 30, tzinfo=timezone.utc)


def build_cache(tmp_path: Path) -> ContributorCache:
    database = tmp_path / "document-contributors.sqlite3"
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
        connection.execute("insert into data values ('Shared', ?)", ("a" * 100 + "b" * 100 + "c" * 200,))
        connection.executemany(
            "insert into user_set values ('pw', ?)",
            (("member-a",), ("member-b",), ("123",)),
        )
        connection.executemany(
            "insert into history values (?, 'Shared', ?, ?, ?, '', ?, '', ?)",
            (
                ("1", "a" * 100, "2026-01-10T00:00:00+09:00", "member-a", "+100", "r1"),
                ("2", "a" * 100 + "b" * 100, "2026-02-10T00:00:00+09:00", "member-b", "+100", ""),
                ("3", "a" * 100 + "b" * 100 + "c" * 200, "2026-03-10T00:00:00+09:00", "123", "+200", ""),
            ),
        )

    @contextmanager
    def connect():
        with sqlite3.connect(database) as connection:
            yield connection

    names = {"member-a": "같은 이름", "member-b": "같은 이름", "123": "123"}
    cache = ContributorCache(
        connect,
        lambda sql: sql,
        lambda _connection, member_id: names[member_id],
        lambda: NOW.timestamp(),
        None,
    )
    cache._refresh()
    return cache


def test_shared_document_ranking_keeps_same_name_accounts_and_private_rank(tmp_path: Path) -> None:
    # Given: two visible accounts share a nickname and have equal raw scores on one document.
    cache = build_cache(tmp_path)

    # When: the second account reads the document contributor snapshot.
    items, generated_at, state, my_rank = cache.document_contributors_snapshot(
        "Shared", "member-b"
    )

    # Then: user-ID tie order keeps separate public rows and the private rank points to row two.
    assert items == (
        {"name": "같은 이름", "url": "/w/user:member-a", "score": 1.56},
        {"name": "같은 이름", "url": "/w/user:member-b", "score": 1.56},
    )
    assert my_rank == {"rank": 2, "score": 1.56}
    assert (generated_at, state) == (int(NOW.timestamp()), "ready")


def test_document_ranking_is_period_scoped_and_hides_numeric_fallback(tmp_path: Path) -> None:
    # Given: the shared document has contributions in three different calendar months.
    cache = build_cache(tmp_path)

    # When: January, unknown month, and unknown document snapshots are read.
    january = cache.document_contributors_snapshot("Shared", "member-a", "2026-01")
    unknown_month = cache.document_contributors_snapshot("Shared", "member-a", "2025-12")
    unknown_document = cache.document_contributors_snapshot("Missing", "member-a")

    # Then: January contains only its author and absent keys keep current cache metadata.
    assert january[0] == ({"name": "같은 이름", "url": "/w/user:member-a", "score": 1.56},)
    assert january[3] == {"rank": 1, "score": 1.56}
    assert unknown_month == ((), int(NOW.timestamp()), "ready", None)
    assert unknown_document == ((), int(NOW.timestamp()), "ready", None)
    assert all(item["name"] != "123" for item in cache.document_contributors_snapshot("Shared", "123")[0])
