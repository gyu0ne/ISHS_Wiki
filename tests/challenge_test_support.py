from __future__ import annotations

import importlib.util
import ast
from html import escape
from urllib.parse import quote
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import flask

from ranking_test_support import ROOT, RankingTestApp, build_test_app


def build_challenge_app(tmp_path: Path) -> RankingTestApp:
    """Run the production challenge route with isolated wiki infrastructure."""
    store = build_test_app(tmp_path)
    with store.connect() as connection:
        connection.execute("create table topic (ip text)")
        connection.execute("create table user_notice (id text, name text, data text, date text, readme text)")
        connection.executemany(
            "insert into contributor_alltime_results (member_id, best_rank) values (?, ?) "
            "on conflict(member_id) do update set best_rank=excluded.best_rank",
            [("20261234", 1), ("20265678", 2)],
        )
    labels = json.loads((ROOT / "lang" / "ko-KR.json").read_text(encoding="utf-8"))
    functions = types.ModuleType("route.tool.func")
    functions.__package__ = "route.tool"

    async def acl_check(**kwargs) -> int:
        return int(kwargs.get("ip") not in flask.current_app.config.get("CHALLENGE_ADMINS", ()))

    async def ip_pas(member_id: str) -> str:
        return escape(member_id)

    async def wiki_set() -> list:
        return ["테스트 위키", "", "", "", "", "", "", ["", "", ""]]

    async def wiki_custom(connection) -> list:
        return ["", "", 1, ""]

    def wiki_css(options) -> list:
        return [0, 0, 0, '<link rel="stylesheet" href="/views/main_css/css/main.css">', "", "", "", 0]

    def render_page(template, **context):
        context["data"] = '<div class="opennamu_main">' + context["data"] + '</div>'
        return flask.render_template(template, **context)

    functions.__dict__.update(
        flask=types.SimpleNamespace(request=flask.request, current_app=flask.current_app, render_template=render_page),
        html=__import__("html"),
        get_db_connect=store.connect,
        db_change=lambda sql: sql,
        ip_check=lambda: flask.session.get("id", "127.0.0.1"),
        ip_or_user=lambda value: int(value == "127.0.0.1"),
        redirect=lambda connection, url: flask.redirect(url),
        get_lang=lambda connection, key, safe=0: labels.get(key, key),
        acl_check=acl_check,
        get_time=lambda: "2026-09-22 12:00:00",
        wiki_set=wiki_set,
        wiki_custom=wiki_custom,
        wiki_css=wiki_css,
        skin_check=lambda connection: "./views/ringo/index.html",
        easy_minify=lambda connection, body: body,
        number_check=lambda value: value,
        url_pas=quote,
        ip_pas=ip_pas,
        get_next_page_bottom=lambda connection, url, number, data: "",
    )
    spec = importlib.util.spec_from_file_location("route.challenge_test_route", ROOT / "route" / "user_challenge.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"route.tool.func": functions}):
        progress_spec = importlib.util.spec_from_file_location("route.tool.challenge_progress", ROOT / "route" / "tool" / "challenge_progress.py")
        assert progress_spec is not None and progress_spec.loader is not None
        progress = importlib.util.module_from_spec(progress_spec)
        progress_spec.loader.exec_module(progress)
        sys.modules[progress_spec.name] = progress
        spec.loader.exec_module(module)
        for filename, url in (("user_alarm", "/alarm"), ("user_alarm_delete", "/alarm/delete/<id>")):
            alarm_spec = importlib.util.spec_from_file_location("route.challenge_test_" + filename, ROOT / "route" / (filename + ".py"))
            assert alarm_spec is not None and alarm_spec.loader is not None
            alarm_module = importlib.util.module_from_spec(alarm_spec)
            alarm_spec.loader.exec_module(alarm_module)
            store.app.add_url_rule(url, view_func=getattr(alarm_module, filename))
    sys.modules[progress_spec.name] = progress
    store.app.add_url_rule("/challenge", view_func=module.user_challenge, methods=["GET", "POST"])
    store.app.jinja_env.filters["load_lang"] = lambda key: labels.get(key, key)
    namespace = dict(functions.__dict__)
    namespace["flask"] = flask

    async def python_to_golang(action: str, options: dict[str, str]) -> dict[str, list[str]]:
        assert action == "api_func_level"
        with store.connect() as connection:
            values = dict(connection.execute("select name, data from user_set where id = ?", [options["ip"]]))
        level = values.get("level", "0")
        return {"data": [level, values.get("experience", "0"), str(500 + int(level) * 50)]}

    namespace["python_to_golang"] = python_to_golang
    tree = ast.parse((ROOT / "route" / "tool" / "func.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "level_check"]
    exec(compile(ast.Module(body=selected, type_ignores=[]), "func.py", "exec"), namespace)

    @store.app.get("/__test/ordinary-page")
    async def ordinary_page():
        level = await namespace["level_check"]()
        with store.connect() as connection:
            notices = connection.execute("select name, id, data from user_notice order by rowid").fetchall()
        return {"level": level, "notices": notices}

    return store
