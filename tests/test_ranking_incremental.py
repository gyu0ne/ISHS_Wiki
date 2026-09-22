from __future__ import annotations

import ast
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

from test_document_contributor_cache import NOW, build_cache
from route.tool.ranking_contributor_cache import ContributorCache
from route.tool.ranking_contributions import HistoryRevision, compute_contribution_scores


def observe_history_reads(cache: ContributorCache) -> list[int]:
    """Count actual history bodies returned by SQLite without replacing its queries."""
    reads: list[int] = []
    original_connect = cache.connect

    def count_row(cursor: sqlite3.Cursor, row: tuple) -> tuple:
        columns = {column[0] for column in cursor.description}
        if {"data", "ip", "hide"} <= columns:
            reads.append(1)
        return row

    @contextmanager
    def connect() -> Iterator[sqlite3.Connection]:
        with original_connect() as connection:
            connection.row_factory = count_row
            yield connection

    cache.connect = connect
    return reads


def restarted(cache: ContributorCache) -> ContributorCache:
    return ContributorCache(
        cache.connect, cache.db_change, cache.get_display_name, cache.clock, None
    )


def assert_full_replay_matches(cache: ContributorCache, database: Path) -> None:
    """Use the source history, not persisted derived state, as the score oracle."""
    with sqlite3.connect(database) as connection:
        documents = cache._documents(connection)
        members = {row[0] for row in connection.execute("select id from user_set where name = 'pw'")}
        revisions = tuple(
            HistoryRevision(
                id=row[0], title=row[1], data=row[2], date=datetime.fromisoformat(row[3]),
                ip=row[4], send=row[5], leng=int(row[6]), hide=row[7], type=row[8],
            )
            for row in connection.execute("select id, title, data, date, ip, send, leng, hide, type from history")
            if row[1] in documents
        )
    scores = compute_contribution_scores(
        revisions, documents, members, datetime.fromtimestamp(cache.clock(), timezone.utc)
    )
    for period in scores.periods():
        visible = [entry for entry in period.scores.contributors if entry.user_id != "123"]
        assert len(cache.snapshot("", period.period)[0]) == len(visible)
        for rank, entry in enumerate(visible, 1):
            assert cache.snapshot(entry.user_id, period.period)[3] == {
                "rank": rank, "score": round(entry.score, 2)
            }


@pytest.mark.parametrize("restart", [False, True], ids=["warm", "restart"])
def test_unchanged_refresh_uses_saved_history_state(tmp_path: Path, restart: bool) -> None:
    # Given: a completed calculation is saved in a real database.
    cache = build_cache(tmp_path)
    expected = cache.snapshot("member-a")
    reads = observe_history_reads(cache)
    refreshed = restarted(cache) if restart else cache

    # When: the same database is refreshed, optionally by a new cache instance.
    refreshed._refresh()

    # Then: the same ranking is available without loading old revision bodies.
    assert refreshed.snapshot("member-a") == expected
    assert reads == []


def test_append_reads_only_new_revision_and_matches_full_replay(tmp_path: Path) -> None:
    # Given: a completed cache and one later committed document revision.
    cache = build_cache(tmp_path)
    reads = observe_history_reads(cache)
    database = tmp_path / "document-contributors.sqlite3"
    with sqlite3.connect(database) as connection:
        body = "a" * 100 + "b" * 100 + "c" * 200 + "d" * 300
        connection.execute("update data set data = ? where title = 'Shared'", (body,))
        connection.execute(
            "insert into history values ('4', 'Shared', ?, '2026-04-29T00:00:00+09:00', 'member-b', '', '+300', '', '')",
            (body,),
        )

    # When: the cache incorporates the edit.
    cache._refresh()

    # Then: its score is the full replay score but only the new body was read.
    assert_full_replay_matches(cache, database)
    assert cache.snapshot("member-b")[3]["rank"] == 1
    assert len(reads) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "update history set ip = 'member-b' where id = '1'",
        "update history set data = replace(data, 'a', 'x') where id = '1'",
        "delete from history where id = '2'",
        "insert into acl values ('Shared', 'owner', 'view')",
        "delete from user_set where id = 'member-a'",
        "update history set title = 'Moved'; update data set title = 'Moved'",
        "update contributor_checkpoints set metadata = '{}'",
        "update contributor_checkpoints set payload = '[]'; update data set data = 'replacement'",
    ],
    ids=["historical-author", "historical-body", "deleted-revision", "private-document", "removed-member", "rename", "invalid-metadata", "invalid-payload"],
)
def test_source_mutations_match_full_replay(tmp_path: Path, mutation: str) -> None:
    # Given: a persisted cache whose source history or eligibility later changes.
    cache = build_cache(tmp_path)
    database = tmp_path / "document-contributors.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(mutation)

    # When: a new process refreshes from that database.
    cache = restarted(cache)
    cache._refresh()

    # Then: persisted state cannot retain stale attribution or private scores.
    assert_full_replay_matches(cache, database)


def test_restoring_current_body_does_not_lose_historical_credit(tmp_path: Path) -> None:
    # Given: current content diverged from history and was already refreshed.
    cache = build_cache(tmp_path)
    expected = cache.snapshot("member-a")
    database = tmp_path / "document-contributors.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("update data set data = '' where title = 'Shared'")
    cache._refresh()
    assert cache.snapshot("member-a")[0] == ()
    with sqlite3.connect(database) as connection:
        connection.execute("update data set data = (select data from history where id = '3')")

    # When: the original current body returns without any history mutation.
    cache = restarted(cache)
    cache._refresh()

    # Then: the temporary body overlay has not destroyed historical ownership.
    assert cache.snapshot("member-a") == expected
    assert_full_replay_matches(cache, database)


def test_empty_sources_clear_saved_rankings(tmp_path: Path) -> None:
    # Given: all source content and membership were removed after a saved ranking.
    cache = build_cache(tmp_path)
    database = tmp_path / "document-contributors.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript("delete from history; delete from data; delete from user_set;")

    # When: the empty source database is refreshed by a new instance.
    cache = restarted(cache)
    cache._refresh()

    # Then: both global and document rankings are empty and ready.
    assert cache.snapshot("member-a") == ((), int(NOW.timestamp()), "ready", None)
    assert cache.document_contributors_snapshot("Shared", "member-a") == (
        (), int(NOW.timestamp()), "ready", None
    )


def test_future_revision_becomes_eligible_without_new_database_writes(tmp_path: Path) -> None:
    cache = build_cache(tmp_path)
    database = tmp_path / "document-contributors.sqlite3"
    body = "a" * 100 + "b" * 100 + "c" * 200 + "d" * 300
    with sqlite3.connect(database) as connection:
        connection.execute("update data set data = ?", (body,))
        connection.execute(
            "insert into history values ('4', 'Shared', ?, '2026-04-30T01:00:00+00:00', 'member-b', '', '+300', '', '')",
            (body,),
        )
    cache._refresh()
    assert_full_replay_matches(cache, database)
    cache.clock = lambda: NOW.timestamp() + 3601
    cache = restarted(cache)
    cache._refresh()
    assert_full_replay_matches(cache, database)
    assert cache.snapshot("member-b")[3] == {"rank": 1, "score": 5.75}


def test_delete_and_restore_after_restart_preserves_original_author(tmp_path: Path) -> None:
    cache = build_cache(tmp_path)
    database = tmp_path / "document-contributors.sqlite3"
    original = "a" * 100 + "b" * 100 + "c" * 200
    extended = original + "d" * 300
    for revision, body, author in ((4, extended, "member-b"), (5, original, "member-a"), (6, extended, "member-a")):
        with sqlite3.connect(database) as connection:
            connection.execute("update data set data = ?", (body,))
            connection.execute(
                "insert into history values (?, 'Shared', ?, ?, ?, '', '300', '', '')",
                (str(revision), body, f"2026-04-29T0{revision}:00:00+09:00", author),
            )
        cache = restarted(cache)
        cache._refresh()
        assert_full_replay_matches(cache, database)
    assert cache.snapshot("member-b")[3] == {"rank": 1, "score": 5.75}
    assert cache.snapshot("member-a")[3] == {"rank": 2, "score": 1.56}


def test_production_autocommit_wrapper_rolls_back_failed_refresh_and_retries(tmp_path: Path) -> None:
    cache = build_cache(tmp_path)
    database = tmp_path / "production.db"
    with sqlite3.connect(tmp_path / "document-contributors.sqlite3") as source:
        with sqlite3.connect(database) as destination:
            source.backup(destination)
    source_path = Path(__file__).resolve().parents[1] / "route/tool/func.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "get_db_connect")
    module = ModuleType("production_db_connection")
    module.sqlite3 = sqlite3
    module.global_some_set_do = lambda name: {"db_type": "sqlite", "db_name": str(database.with_suffix(""))}[name]
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source_path), "exec"), module.__dict__)
    cache.connect = module.get_db_connect
    expected = cache.snapshot("member-a")
    with cache.connect() as connection:
        generation = connection.execute("select generation from contributor_checkpoint_state").fetchone()[0]
        connection.execute("update history set ip = 'member-b' where id = '1'")
        connection.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON contributor_checkpoints BEGIN SELECT RAISE(ABORT, 'checkpoint rejected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="checkpoint rejected"):
        cache._refresh()
    assert cache.snapshot("member-a") == expected
    with cache.connect() as connection:
        assert connection.execute("select generation from contributor_checkpoint_state").fetchone()[0] == generation
        assert connection.execute("select count(*) from contributor_history_changes").fetchone()[0] > 0
        connection.execute("drop trigger fail_checkpoint")
    cache = restarted(cache)
    cache._refresh()
    assert_full_replay_matches(cache, database)
    assert cache.snapshot("member-a")[3] is None


@pytest.mark.parametrize('format_name', ['legacy', 'broken-json', 'broken-compression'])
def test_old_or_broken_checkpoint_is_resaved_compressed(tmp_path: Path, format_name: str) -> None:
    import zlib
    from base64 import b64decode
    from route.tool.ranking_contribution_engine import DocumentContributionEngine

    cache = build_cache(tmp_path)
    database = tmp_path / 'document-contributors.sqlite3'
    with sqlite3.connect(database) as connection:
        saved = connection.execute('select payload from contributor_checkpoints').fetchone()[0]
        replacements = {
            'legacy': zlib.decompress(b64decode(saved[5:])).decode(),
            'broken-json': '[]',
            'broken-compression': 'zlib:!',
        }
        connection.execute('update contributor_checkpoints set payload = ?', (replacements[format_name],))
        connection.execute("update data set data = data || '!' where title = 'Shared'")
    cache = restarted(cache)
    cache._refresh()
    assert_full_replay_matches(cache, database)
    with sqlite3.connect(database) as connection:
        resaved = connection.execute('select payload from contributor_checkpoints').fetchone()[0]
    assert resaved.startswith('zlib:')
    restored = DocumentContributionEngine.load_checkpoint(resaved)
    assert restored.text
