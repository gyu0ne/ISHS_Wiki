from __future__ import annotations

import importlib.util
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
    labels = json.loads((ROOT / "lang" / "ko-KR.json").read_text(encoding="utf-8"))
    functions = types.ModuleType("route.tool.func")
    functions.__package__ = "route.tool"

    async def acl_check(**kwargs) -> int:
        return 1

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
        wiki_set=wiki_set,
        wiki_custom=wiki_custom,
        wiki_css=wiki_css,
        skin_check=lambda connection: "./views/ringo/index.html",
        easy_minify=lambda connection, body: body,
    )
    spec = importlib.util.spec_from_file_location("route.challenge_test_route", ROOT / "route" / "user_challenge.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"route.tool.func": functions}):
        spec.loader.exec_module(module)
    store.app.add_url_rule("/challenge", view_func=module.user_challenge, methods=["GET", "POST"])
    store.app.jinja_env.filters["load_lang"] = lambda key: labels.get(key, key)
    return store
