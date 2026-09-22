from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from challenge_test_support import build_challenge_app


def test_settings_save_when_achievement_notice_storage_fails(tmp_path: Path) -> None:
    # Given an unavailable achievement notice store and an authenticated member.
    store = build_challenge_app(tmp_path)
    with store.connect() as connection:
        connection.execute("create trigger fail_notice before insert on user_notice begin select raise(FAIL, 'test failure'); end")
    client = store.app.test_client()
    client.get("/__test/login/20261234")

    # When ordinary profile preferences are saved through the production route.
    response = client.post("/change", data={"skin": "ringo", "lang": "en-US", "user_title": "🌳"})

    # Then preferences persist without attempting an achievement grant.
    assert response.status_code == 302
    with store.connect() as connection:
        values = dict(connection.execute("select name, data from user_set where id='20261234'"))
        assert (values["skin"], values["lang"], values["user_title"]) == ("ringo", "en-US", "🌳")
        assert "challenge_first_contribute" not in values


def test_repeated_browsing_skips_refresh_queries_until_cooldown_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given one successful automatic refresh.
    store = build_challenge_app(tmp_path)
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    first = client.get("/__test/ordinary-page").json
    statements: list[str] = []
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)

    # When more pages are read before 60 seconds have elapsed.
    store.clock.value += 59
    for _ in range(3):
        assert client.get("/__test/ordinary-page").json == first

    # Then no ranking/activity queries or write transactions run.
    assert not any("BEGIN IMMEDIATE" in sql or "winners" in sql or "count(*)" in sql for sql in statements)
    with store.connect() as connection:
        connection.execute("insert into topic values ('20261234')")
    store.clock.value += 1
    refreshed = client.get("/__test/ordinary-page").json
    assert len(refreshed["notices"]) == len(first["notices"]) + 1
    assert any("BEGIN IMMEDIATE" in sql for sql in statements)


def test_explicit_challenge_page_refreshes_during_cooldown(tmp_path: Path) -> None:
    # Given a recently refreshed member who has just posted a discussion.
    store = build_challenge_app(tmp_path)
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    first = client.get("/__test/ordinary-page").json
    with store.connect() as connection:
        connection.execute("insert into topic values ('20261234')")

    # When the member explicitly opens the achievement page.
    assert client.get("/challenge").status_code == 200

    # Then the new achievement is immediately persisted once.
    assert len(client.get("/__test/ordinary-page").json["notices"]) == len(first["notices"]) + 1


def test_older_refresh_cannot_overwrite_new_ranking_reward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given an older request paused at its ACL await before a newer rank grant.
    store = build_challenge_app(tmp_path)
    progress = sys.modules["route.tool.challenge_progress"]
    original_acl = progress.acl_check
    newer_values: dict[str, str] = {}

    async def publish_award_during_acl(**kwargs) -> int:
        with store.connect() as connection:
            connection.execute("insert into contributor_monthly_results values (?, ?)",
                               ["2026-01", json.dumps(["20261234"])])
        monkeypatch.setattr(progress, "acl_check", original_acl)
        with store.app.test_request_context("/challenge"):
            with store.connect() as connection:
                await progress.refresh_challenges(connection, "20261234")
                newer_values.update(connection.execute(
                    "select name, data from user_set where id='20261234' and name in ('level', 'experience')"))
        return 1

    monkeypatch.setattr(progress, "acl_check", publish_award_during_acl)
    client = store.app.test_client()
    client.get("/__test/login/20261234")

    # When the older request resumes and commits after the new grant.
    assert client.get("/__test/ordinary-page").status_code == 200

    # Then the newer ranking reward and its notices remain intact.
    with store.connect() as connection:
        values = dict(connection.execute(
            "select name, data from user_set where id='20261234' and name in ('level', 'experience')"))
        assert values == newer_values
        assert connection.execute("select count(*) from user_notice where id='challenge_monthly_first'").fetchone()[0] == 1


def test_unchanged_refresh_succeeds_while_another_writer_holds_lock(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    with store.connect() as connection:
        connection.execute("pragma journal_mode=WAL")
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    expected = client.get("/__test/ordinary-page").json
    store.clock.value += 60
    with store.connect() as writer:
        writer.execute("BEGIN IMMEDIATE")
        assert client.get("/__test/ordinary-page").json == expected


def test_challenge_indexes_support_member_queries_and_repeated_startup(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    progress = sys.modules["route.tool.challenge_progress"]
    with store.connect() as connection:
        progress.ensure_challenge_indexes(connection)
        progress.ensure_challenge_indexes(connection)
        for table, column in (("history", "ip"), ("topic", "ip"), ("user_set", "id")):
            plans = connection.execute(f"EXPLAIN QUERY PLAN SELECT count(*) FROM {table} WHERE {column}=?", ["20261234"]).fetchall()
            assert any("SEARCH" in row[3] and "INDEX" in row[3] for row in plans), plans


def test_write_pass_rechecks_awards_changed_after_read_only_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = build_challenge_app(tmp_path)
    progress = sys.modules["route.tool.challenge_progress"]
    read_awards = progress.earned_ranking_challenges

    def publish_after_read(connection, member_id, sql):
        stale = read_awards(connection, member_id, sql)
        monkeypatch.setattr(progress, "earned_ranking_challenges", read_awards)
        with store.connect() as publisher:
            publisher.execute("insert into contributor_monthly_results values (?,?)", ["2026-01", json.dumps([member_id])])
        return stale

    monkeypatch.setattr(progress, "earned_ranking_challenges", publish_after_read)
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    assert client.get("/__test/ordinary-page").status_code == 200
    with store.connect() as connection:
        values = dict(connection.execute("select name,data from user_set where id='20261234'"))
        assert (values["level"], values["experience"]) == ("15", "760")
        assert values["challenge_monthly_first"] == "1"
