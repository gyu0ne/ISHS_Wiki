from __future__ import annotations

import anyio
from contextlib import contextmanager
import json
import os
import sys
import threading
from typing import Iterator
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import flask
from werkzeug.serving import make_server

from security_fixture_server import ROOT, SecurityFixture, security_fixture
from security_support import load_source_definitions


PRIVATE_FIELDS = {"student_id", "real_name", "birth", "gender", "generation"}
CACHE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


@contextmanager
def user_info_app() -> Iterator[tuple[flask.Flask, dict[str, int], SecurityFixture]]:
    with security_fixture() as fixture:
        with fixture.connect() as conn:
            conn.execute("create table user_set (id text, name text, data text)")
            conn.execute("create table data (title text)")
            conn.execute("insert into data values (?)", ("user:target",))
            conn.executemany(
                "insert into user_set values (?, ?, ?)",
                [
                    ("target", "acl", "member"), ("target", "auth_date", "0"),
                    ("target", "user_title", ""), ("target", "student_id", "S-TEST-01"),
                    ("target", "real_name", "Synthetic Name"), ("target", "birth_year", "2000"),
                    ("target", "birth_month", "01"), ("target", "birth_day", "02"),
                    ("target", "gender", "female"), ("target", "generation", "test"),
                ],
            )

        state = {"connect_calls": 0}

        def counted_connect():
            state["connect_calls"] = int(state["connect_calls"]) + 1
            return fixture.connect()

        async def ip_pas(value: str) -> str:
            return value

        async def level_check(_value: str) -> tuple[str, str, str]:
            return ("1", "0", "1")

        async def ban_check(_value: str) -> tuple[int]:
            return (0,)

        async def acl_check(tool: str = "") -> int:
            return 0 if flask.session.get("id") == "admin" and tool in {"owner_auth", "ban_auth"} else 1

        loaded = load_source_definitions(
            ROOT / "route" / "api_user_info.py",
            ("api_user_info",),
            {
                "flask": flask,
                "get_db_connect": counted_connect,
                "db_change": lambda query: query,
                "ip_pas": ip_pas,
                "ip_or_user": lambda _value: 0,
                "level_check": level_check,
                "ban_check": ban_check,
                "acl_check": acl_check,
                "get_lang": lambda _conn, key: key,
            },
        )
        handler = loaded.definitions["api_user_info"]
        @fixture.app.get("/api/user_info/<user_name>")
        def api_route(user_name: str):
            return anyio.run(handler, user_name)

        @fixture.app.get("/qa/<mode>")
        def qa_page(mode: str):
            flask.session.clear()
            if mode == "member":
                flask.session["id"] = "member"
            return flask.Response(
                """<!doctype html><meta charset=\"utf-8\"><div id=\"opennamu_get_user_info\">target</div>
                <script>
                function opennamu_do_url_encode(value) { return encodeURIComponent(value); }
                function opennamu_xss_filter(value) { return value; }
                </script><script src=\"/views/main_css/js/func/insert_user_info.js\"></script>""",
                mimetype="text/html",
            )

        @fixture.app.get("/views/main_css/js/func/insert_user_info.js")
        def user_info_script():
            return flask.send_file(ROOT / "views" / "main_css" / "js" / "func" / "insert_user_info.js")

        yield fixture.app, state, fixture


class UserInfoSecurityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.apps = user_info_app()
        self.app, self.state, self.fixture = self.apps.__enter__()
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.apps.__exit__(None, None, None)

    def get(self, session_values: dict[str, str | int] | None = None) -> flask.Response:
        with self.client.session_transaction() as session:
            session.clear()
            if session_values:
                session.update(session_values)
        return self.client.get("/api/user_info/target")

    def test_member_profile_contract_is_preserved(self) -> None:
        response = self.get({"id": "member"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()["data"]
        self.assertEqual({key: data[key] for key in PRIVATE_FIELDS}, {
            "student_id": "S-TEST-01", "real_name": "Synthetic Name", "birth": "2000-01-02",
            "gender": "female", "generation": "test",
        })
        self.assertEqual(data["viewer_is_admin"], 0)

    def test_admin_profile_contract_is_preserved(self) -> None:
        response = self.get({"id": "admin"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["viewer_is_admin"], 1)

    def test_anonymous_and_intermediate_sessions_are_denied_before_profile_work(self) -> None:
        for session_values in ({}, {"id": ""}, {"id": 1}, {"login_id": "member"}, {"user_name": "member"}):
            with self.subTest(session_values=session_values):
                self.state["connect_calls"] = 0
                response = self.get(session_values)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.get_json(), {"error": "login_required"})
                self.assertEqual(set(response.get_json()), {"error"})
                self.assertEqual(self.state["connect_calls"], 0)

    def test_every_response_is_private_and_cookie_varying(self) -> None:
        for session_values, expected_status in (({}, 401), ({"id": "member"}, 200), ({"id": "admin"}, 200)):
            with self.subTest(session_values=session_values):
                response = self.get(session_values)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual({name: response.headers[name] for name in CACHE_HEADERS}, CACHE_HEADERS)


def http_observation():
    with user_info_app() as (app, _state, fixture):
        fixture_root = fixture.root
        server = make_server("127.0.0.1", 0, app)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            anonymous_request = Request(base + "/api/user_info/target")
            try:
                urlopen(anonymous_request, timeout=5)
            except HTTPError as error:
                anonymous = error
            else:
                raise AssertionError("anonymous request unexpectedly succeeded")

            serializer = app.session_interface.get_signing_serializer(app)
            if serializer is None:
                raise AssertionError("synthetic session serializer missing")
            cookie = serializer.dumps({"id": "member"})
            member_response = urlopen(Request(base + "/api/user_info/target", headers={"Cookie": f"session={cookie}"}), timeout=5)
            member_payload = json.loads(member_response.read())
            observation = {
                "anonymous_status": getattr(anonymous, "code", None),
                "anonymous_body_keys": sorted(json.loads(anonymous.read()).keys()),
                "member_status": member_response.status,
                "member_private_field_names": sorted(PRIVATE_FIELDS & set(member_payload["data"])),
                "member_cache_headers": {name: member_response.headers[name] for name in CACHE_HEADERS},
            }
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            if thread.is_alive():
                raise AssertionError("loopback server thread did not stop")
    observation["fixture_root_removed_after_context"] = not fixture_root.exists()
    return observation


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        with user_info_app() as (app, _state, _fixture):
            server = make_server("127.0.0.1", 8769, app)
            print(json.dumps({"host": "127.0.0.1", "port": server.server_port, "pid": os.getpid()}), flush=True)
            server.serve_forever()
    else:
        print(json.dumps(http_observation(), ensure_ascii=False, sort_keys=True))
