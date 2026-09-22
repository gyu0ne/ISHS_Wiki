from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from challenge_test_support import build_challenge_app
from ranking_test_support import ROOT
from route.tool.ranking_challenges import RANKING_CHALLENGES
from route.tool.ranking_monthly_awards import MonthlyAwards


@pytest.mark.parametrize("rank,wins,keys", [
    (None, 0, ()),
    (11, 0, ()),
    (10, 0, ()),
    (3, 0, ("monthly_top3",)),
    (1, 1, ("monthly_top3", "monthly_first")),
    (1, 2, ("monthly_top3", "monthly_first", "monthly_first_twice")),
])
def test_monthly_rank_achievements(rank: int | None, wins: int, keys: tuple[str, ...]) -> None:
    awards = MonthlyAwards(rank, wins)
    assert tuple(item.key for item in RANKING_CHALLENGES if item.achieved(awards)) == keys


def test_challenge_route_rewards_titles_and_refresh_are_consistent(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    client = store.app.test_client()
    assert client.get("/challenge").status_code == 302
    client.get("/__test/login/20261234")
    locked = client.get("/challenge").get_data(as_text=True)
    assert "어, 또 나야" in locked
    assert "시작이 반이다." in locked
    with store.connect() as connection:
        baseline = dict(connection.execute("select name, data from user_set where id='20261234' and name in ('level','experience')"))
        assert set(baseline) == {"level", "experience"}
        for period in ("2026-01", "2026-03"):
            connection.execute("insert into contributor_monthly_results values (?, ?)", (period, json.dumps(["20261234"])))
    earned = client.get("/challenge").get_data(as_text=True)
    for title in ("시상대는 처음이라", "정상은 좀 덥네", "어, 또 나야"):
        assert title in earned
    results = []
    for _ in range(2):
        assert client.get("/challenge").status_code == 200
        with store.connect() as connection:
            results.append(dict(connection.execute("select name, data from user_set where id='20261234' and name in ('level','experience')")))
    def total(values: dict[str, str]) -> int:
        level = int(values["level"])
        return 500 * level + 25 * level * (level - 1) + int(values["experience"])
    assert results[0] == results[1]
    assert total(results[0]) - total(baseline) == 9000
    # Execute the actual title-selector function without func.py's application startup side effects.
    tree = ast.parse((ROOT / "route" / "tool" / "func.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_user_title_list")
    namespace = dict(store.app.view_functions["user_challenge"].__globals__)
    namespace["__package__"] = "route.tool"
    namespace["__spec__"] = None
    exec(compile(ast.Module(body=[function], type_ignores=[]), "func.py", "exec"), namespace)
    async def available_titles():
        with store.connect() as connection:
            return (
                await namespace["get_user_title_list"](connection, "20261234"),
                await namespace["get_user_title_list"](connection, "20265678"),
            )
    with store.app.test_request_context("/user_setting"):
        titles, other_titles = store.app.ensure_sync(available_titles)()
    assert all(item.title in titles for item in RANKING_CHALLENGES)
    assert all(item.title not in other_titles for item in RANKING_CHALLENGES if not item.alltime)
    assert "🐐" not in other_titles
    assert "🔰" in titles


@pytest.mark.parametrize("rankings_enabled", [True, False])
def test_challenge_get_updates_activity_without_manual_refresh(tmp_path: Path, rankings_enabled: bool) -> None:
    store = build_challenge_app(tmp_path)
    if not rankings_enabled:
        store.app.extensions.pop("rankings")
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    assert client.get("/challenge").status_code == 200
    with store.connect() as connection:
        badges = dict(connection.execute("select name, data from user_set where id='20261234'"))
        assert badges["challenge_first_contribute"] == "1"
        assert "challenge_first_discussion" not in badges
        connection.executemany("insert into topic values (?)", [("20261234",)] * 10)
    results = []
    for _ in range(2):
        assert client.get("/challenge").status_code == 200
        with store.connect() as connection:
            results.append(dict(connection.execute("select name, data from user_set where id='20261234'")))
    assert results[0] == results[1]
    assert results[0]["challenge_first_discussion"] == "1"
    assert results[0]["challenge_tenth_discussion"] == "1"
    assert results[0]["level"] != badges["level"]


def test_existing_challenges_still_work_when_rankings_are_disabled(tmp_path: Path) -> None:
    store = build_challenge_app(tmp_path)
    store.app.extensions.pop("rankings")
    with store.connect() as connection:
        connection.execute("drop table contributor_monthly_results")
    client = store.app.test_client()
    client.get("/__test/login/20261234")
    assert client.get("/challenge").status_code == 200
    assert client.post("/challenge").status_code == 302


@pytest.mark.parametrize("rank,keys", [(None, ()), (11, ()), (10, ("alltime_top10",)), (3, ("alltime_top10", "alltime_top3")), (1, ("alltime_top10", "alltime_top3", "alltime_first"))])
def test_alltime_rank_achievements(rank: int | None, keys: tuple[str, ...]) -> None:
    awards = MonthlyAwards(alltime_best_rank=rank)
    assert tuple(item.key for item in RANKING_CHALLENGES if item.achieved(awards)) == keys
    assert len(RANKING_CHALLENGES) == 6
