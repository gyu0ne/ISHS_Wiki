from __future__ import annotations

import json
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from challenge_test_support import build_challenge_app
from ranking_test_support import ROOT


@pytest.mark.parametrize("rankings_enabled", [True, False])
def test_normal_browsing_refreshes_progress_and_notifies_once(tmp_path: Path, rankings_enabled: bool) -> None:
    store = build_challenge_app(tmp_path)
    if not rankings_enabled:
        store.app.extensions.pop("rankings")
    client = store.app.test_client()
    assert client.get("/__test/ordinary-page").json["notices"] == []
    client.get("/__test/login/20261234")
    first = client.get("/__test/ordinary-page").json
    assert int(first["level"][0]) > 0
    assert len(first["notices"]) == (4 if rankings_enabled else 1)
    assert first["notices"][0][0] == "20261234"
    assert "도전과제 달성!" in first["notices"][0][2]
    assert any("시작이 반이다." in notice[2] for notice in first["notices"])
    assert 'href="/challenge"' in first["notices"][0][2]
    with store.connect() as connection:
        connection.executemany("insert into topic values (?)", [("20261234",)] * 10)
        if rankings_enabled:
            connection.execute("insert into contributor_monthly_results values (?, ?)",
                               ["2026-01", json.dumps(["20261234"])])
    store.clock.value += 60
    second = client.get("/__test/ordinary-page").json
    assert int(second["level"][0]) > int(first["level"][0])
    assert len(second["notices"]) == len(first["notices"]) + (4 if rankings_enabled else 2)
    assert any("진실은 보통" in notice[2] for notice in second["notices"])
    if rankings_enabled:
        assert any("정상은 좀 덥네" in notice[2] for notice in second["notices"])
    assert client.get("/__test/ordinary-page").json == second
    alarm_page = client.get("/alarm")
    assert alarm_page.status_code == 200
    assert "시작이 반이다." in alarm_page.get_data(as_text=True)
    assert client.get("/alarm/delete/challenge_first_contribute").status_code == 302
    assert all("시작이 반이다." not in notice[2] for notice in client.get("/__test/ordinary-page").json["notices"])
    with store.connect() as connection:
        connection.execute("delete from user_notice")
    assert client.get("/__test/ordinary-page").json["notices"] == []
    assert client.get("/challenge").status_code == 200
    assert client.get("/__test/ordinary-page").json["notices"] == []


def test_existing_achievements_and_admin_status_use_the_target_member(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    store.app.extensions.pop("rankings")
    store.app.config["CHALLENGE_ADMINS"] = {"20261234"}
    with store.connect() as connection:
        connection.execute("insert into user_set values ('challenge_first_contribute', '20261234', '1')")
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    result = client.get("/__test/ordinary-page").json
    assert len(result["notices"]) == 1
    assert "왕후장상의" in result["notices"][0][2]
    assert "시작이 반이다." not in result["notices"][0][2]
    store.app.config["CHALLENGE_ADMINS"] = set()
    assert client.get("/__test/ordinary-page").json == result


def test_concurrent_refreshes_create_one_notice_per_achievement(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    store.app.extensions.pop("rankings")

    def browse(_: int) -> int:
        client = store.app.test_client()
        client.get("/__test/login/20261234")
        return client.get("/__test/ordinary-page").status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(browse, range(8))) == [200] * 8
    with store.connect() as connection:
        assert connection.execute("select count(*) from user_notice").fetchone()[0] == 1
        assert connection.execute("select count(*) from user_set where name='challenge_first_contribute'").fetchone()[0] == 1


def test_failed_notice_insert_rolls_back_unlock_and_retries(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    store.app.extensions.pop("rankings")
    with store.connect() as connection:
        connection.execute("create trigger fail_notice before insert on user_notice begin select raise(FAIL, 'test failure'); end")
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    assert client.get("/__test/ordinary-page").status_code == 500
    with store.connect() as connection:
        assert connection.execute("select count(*) from user_set where name='challenge_first_contribute'").fetchone()[0] == 0
        connection.execute("drop trigger fail_notice")
    assert len(client.get("/__test/ordinary-page").json["notices"]) == 1


def test_acl_backend_error_does_not_grant_admin_permission(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    tree = ast.parse((ROOT / "route" / "tool" / "func.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "acl_check"]

    async def unavailable_backend(action: str, options: dict[str, str]) -> dict[str, str]:
        return {"response": "error", "data": "Go backend connection failed."}

    namespace = {"python_to_golang": unavailable_backend}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "func.py", "exec"), namespace)
    assert store.app.ensure_sync(namespace["acl_check"])(tool="all_admin_auth", ip="20261234") == 1


def test_normal_page_keeps_rank_xp_when_rank_table_vanishes(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    client = store.app.test_client()
    with store.connect() as connection:
        connection.execute("insert into contributor_monthly_results values (?, ?)",
                           ["2026-01", json.dumps(["20261234"])])
    client.get("/__test/login/20261234")
    assert client.get("/__test/ordinary-page").status_code == 200
    with store.connect() as connection:
        previous = dict(connection.execute(
            "select name, data from user_set where id = ? and name in ('level', 'experience')",
            ["20261234"],
        ))
        assert connection.execute(
            "select 1 from user_set where id = ? and name = 'challenge_monthly_first'",
            ["20261234"],
        ).fetchone()
        connection.execute("drop table contributor_monthly_results")

    store.clock.value += 60
    response = client.get("/__test/ordinary-page")
    assert response.status_code == 200
    assert response.json["level"][:2] == [previous["level"], previous["experience"]]
    with store.connect() as connection:
        assert dict(connection.execute(
            "select name, data from user_set where id = ? and name in ('level', 'experience')",
            ["20261234"],
        )) == previous
