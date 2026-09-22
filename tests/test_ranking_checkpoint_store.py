from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from ranking_package_support import bootstrap_route_tool_package

bootstrap_route_tool_package()


from route.tool import ranking_checkpoint_store as store


def connection(path: Path):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS history (title TEXT, id TEXT, data TEXT)")
    return db


def test_checkpoint_survives_restart_and_tracks_direct_history_changes(tmp_path):
    with connection(tmp_path / "cache.db") as db:
        store.ensure_schema(db, str)
        db.execute("INSERT INTO history VALUES ('A', '1', 'old')")
        before = store.snapshot(db, str)
        assert [(e.title, e.kind) for e in before.events] == [("A", "append")]
        assert store.publish(
            db,
            str,
            before,
            (store.CheckpointWrite("A", "meta", "payload"),),
            (),
            "members",
        )
    with connection(tmp_path / "cache.db") as db:
        store.ensure_schema(db, str)
        db.execute("UPDATE history SET title = 'B', data = 'changed' WHERE title = 'A'")
        after = store.snapshot(db, str)
        assert after.checkpoints == {"A": "meta"}
        assert store.load_checkpoint(db, str, "A") == "payload"
        assert {(e.title, e.kind) for e in after.events} == {
            ("A", "rebuild"),
            ("B", "rebuild"),
        }


def test_publish_keeps_later_edits_and_rejects_stale_generation(tmp_path):
    with connection(tmp_path / "cache.db") as db:
        store.ensure_schema(db, str)
        before = store.snapshot(db, str)
        db.execute("INSERT INTO history VALUES ('A', '1', 'new')")
        assert store.publish(db, str, before, (), (), "members")
        assert not store.publish(db, str, before, (), (), "stale")
        after = store.snapshot(db, str)
        assert after.member_hash == "members"
        assert len(after.events) == 1
        assert after.processed_seq == before.watermark


def test_publish_rolls_back_partial_payload_writes(tmp_path):
    with connection(tmp_path / "cache.db") as db:
        store.ensure_schema(db, str)
        before = store.snapshot(db, str)
        db.execute(
            "CREATE TRIGGER reject_bad BEFORE INSERT ON contributor_checkpoints WHEN NEW.title = 'bad' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="test failure"):
            store.publish(
                db,
                str,
                before,
                (
                    store.CheckpointWrite("ok", "m", "p"),
                    store.CheckpointWrite("bad", "m", "p"),
                ),
                (),
                "members",
            )
        db.commit()  # The production connection context commits even after exceptions.
        after = store.snapshot(db, str)
        assert after.generation == before.generation
        assert after.checkpoints == {}


def test_external_connection_delete_is_tracked_and_rolled_back_edit_is_not(tmp_path):
    path = tmp_path / "cache.db"
    with connection(path) as reader, connection(path) as writer:
        store.ensure_schema(reader, str)
        writer.execute("INSERT INTO history VALUES ('A', '1', 'old')")
        before = store.snapshot(reader, str)
        writer.execute("BEGIN")
        writer.execute("UPDATE history SET data = 'never committed'")
        writer.rollback()
        writer.execute("DELETE FROM history WHERE title = 'A'")
        assert store.publish(reader, str, before, (), (), "members")
        after = store.snapshot(reader, str)
        assert [(e.title, e.kind) for e in after.events] == [("A", "rebuild")]
        assert after.watermark == before.watermark + 1


@pytest.mark.parametrize(
    "expected, code", [(1061, 1061), (1359, 1359), (1061, 1359), (1359, 1142)]
)
def test_mysql_schema_race_only_ignores_matching_existing_object(expected, code):
    from pymysql.err import OperationalError

    from route.tool import ranking_checkpoint_schema

    class RacingCursor:
        def execute(self, statement, parameters=()):
            raise OperationalError(code, "DDL race or permission denial")

    create = ranking_checkpoint_schema._create_mysql_object
    if code == expected:
        create(RacingCursor(), "CREATE INDEX example ON table_name (seq)", expected)
    else:
        with pytest.raises(OperationalError):
            create(RacingCursor(), "CREATE INDEX example ON table_name (seq)", expected)
