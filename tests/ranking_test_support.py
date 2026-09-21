from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from flask import Flask, current_app, render_template, session


ROOT = Path(__file__).resolve().parents[1]


class RankingModuleLoadError(RuntimeError):
    pass


def _load_rankings_module():
    route_package = sys.modules.setdefault("route", types.ModuleType("route"))
    route_package.__path__ = [str(ROOT / "route")]
    tool_package = sys.modules.setdefault("route.tool", types.ModuleType("route.tool"))
    tool_package.__path__ = [str(ROOT / "route" / "tool")]
    spec = importlib.util.spec_from_file_location("route.rankings", ROOT / "route" / "rankings.py")
    if spec is None or spec.loader is None:
        raise RankingModuleLoadError
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestClock:
    def __init__(self) -> None:
        self.value = 2_000_000_000

    def __call__(self) -> float:
        return float(self.value)


@dataclass(frozen=True, slots=True)
class RankingTestApp:
    app: Flask
    db_path: Path
    clock: TestClock

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()


def _seed_database(db_path: Path) -> None:
    mature = datetime.fromtimestamp(2_000_000_000) - timedelta(days=10)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            create table data (title text, data text, type text);
            create table back (title text, link text, type text, data text);
            create table acl (title text, data text, type text);
            create table user_set (name text, id text, data text);
            create table history (
                id text, title text, data text, date text, ip text,
                send text, leng text, hide text, type text
            );
            """
        )
        connection.executemany(
            "insert into data values (?, ?, '')",
            (
                ("Public Page", "A" * 1200),
                ("Second Page", "B" * 900),
                ("Private Page", "secret" * 300),
                ("Deleted Later", "temporary"),
            ),
        )
        connection.execute("insert into acl values ('Private Page', 'member-group', 'view')")
        connection.executemany(
            "insert into user_set values (?, ?, ?)",
            (
                ("pw", "20261234", "hash"),
                ("user_name", "20261234", "별빛"),
                ("generation", "20261234", "32"),
                ("riro_reauthed", "20261234", "1"),
                ("pw", "20265678", "hash"),
                ("user_name", "20265678", "달빛"),
                ("generation", "20265678", "32"),
                ("riro_reauthed", "20265678", "1"),
            ),
        )
        connection.executemany(
            "insert into history values (?, ?, ?, ?, ?, '', ?, '', '')",
            (
                ("1", "Public Page", "A" * 1200, mature.strftime("%Y-%m-%d %H:%M:%S"), "20261234", "+1200"),
                ("1", "Second Page", "B" * 900, mature.strftime("%Y-%m-%d %H:%M:%S"), "20265678", "+900"),
                ("1", "Private Page", "secret" * 300, mature.strftime("%Y-%m-%d %H:%M:%S"), "20261234", "+1800"),
            ),
        )


def build_test_app(tmp_path: Path, seed_extra: Callable[[Path], None] | None = None) -> RankingTestApp:
    rankings = _load_rankings_module()
    db_path = tmp_path / "rankings.sqlite3"
    _seed_database(db_path)
    if seed_extra is not None:
        seed_extra(db_path)
    clock = TestClock()
    app = Flask(__name__, template_folder=str(ROOT))
    app.secret_key = "ranking-test-secret"
    app.config["RANKING_CONNECT_CALLS"] = 0
    app.jinja_env.filters["load_lang"] = lambda value: value
    app.jinja_env.globals["cache_v"] = lambda: ""

    @contextmanager
    def connect():
        app.config["RANKING_CONNECT_CALLS"] += 1
        connection = sqlite3.connect(db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    async def acl_check(title: str, tool: str) -> int:
        assert tool == "render"
        return int(title == "Private Page" or (title == "" and bool(current_app.config.get("DENY_GLOBAL_RENDER"))))

    def display_name(connection: sqlite3.Connection, user_id: str) -> str:
        row = connection.execute(
            "select data from user_set where id = ? and name = 'user_name'", (user_id,)
        ).fetchone()
        return row[0] if row else user_id

    def member_is_eligible(connection: sqlite3.Connection, user_id: str) -> bool:
        generation = connection.execute(
            "select data from user_set where id = ? and name = 'generation'", (user_id,)
        ).fetchone()
        if not generation or generation[0] not in {"30", "31", "32"}:
            return True
        verified = connection.execute(
            "select data from user_set where id = ? and name = 'riro_reauthed'", (user_id,)
        ).fetchone()
        return bool(verified and verified[0] == "1")

    async def render_page(title: str, body: str):
        wiki = ["테스트 위키", "", "", "", "", "", "", ["", "", ""]]
        custom = ["", "", 1, ""]
        assets = '<link rel="stylesheet" href="/views/main_css/css/main.css"><script defer src="/views/main_css/js/func/func.js"></script>'
        css = [0, 0, 0, assets, "", "", "", 0]
        return render_template(
            "./views/ringo/index.html",
            imp=[title, wiki, custom, css],
            data=body,
            menu=0,
            adsense_enabled=False,
            recent_sidebar="",
            trending_sidebar="",
            discussion_sidebar="",
            ranking_ticket="",
        )

    rankings.init_rankings(
        app,
        connect=connect,
        db_change=lambda sql: sql,
        acl_check=acl_check,
        get_display_name=display_name,
        render_page=render_page,
        member_is_eligible=member_is_eligible,
        clock=clock,
        contributor_refresh_seconds=None,
    )
    if not rankings.wait_for_contributor_refresh(app):
        raise RankingModuleLoadError

    @app.get("/__test/login/<user_id>")
    def login(user_id: str):
        session.clear()
        session["id"] = user_id
        return "ok"

    @app.get("/__test/ticket/<path:title>")
    def ticket(title: str):
        return {"ticket": rankings.issue_ranking_ticket(title)}

    return RankingTestApp(app=app, db_path=db_path, clock=clock)


def seed_popular(store: RankingTestApp, title: str, members: tuple[str, ...], viewed_at: int | None = None) -> None:
    rankings = sys.modules["route.rankings"]
    at = store.clock.value if viewed_at is None else viewed_at
    with store.connect() as connection:
        for member in members:
            rankings.record_view(connection, title, title, member, at, lambda sql: sql)


def origin_headers() -> dict[str, str]:
    return {"Origin": "http://localhost", "Content-Type": "application/json"}


def encoded(value: str) -> str:
    return quote(value, safe="")
