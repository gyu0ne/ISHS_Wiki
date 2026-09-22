# noqa: SIZE_OK
from __future__ import annotations

import anyio
from collections.abc import Callable
from pathlib import Path
import sqlite3
import time
import datetime
import hashlib
import html
import json
import re
import sys
import unicodedata
import unittest

import flask as flask_module

from security_fixture_server import SecurityFixture, security_fixture
from security_support import LoadedSource, load_source_definitions
from werkzeug.serving import make_server


ROOT = Path(__file__).resolve().parents[1]


class SourceDefinitionError(TypeError):
    pass


class FlaskFacade:
    @property
    def request(self):
        return flask_module.request

    @property
    def session(self):
        return flask_module.session

    @staticmethod
    def make_response(value):
        return flask_module.make_response(value)

    @staticmethod
    def render_template(_name, **kwargs):
        return kwargs.get("data", "")


async def _allow_ban(*_args, **_kwargs):
    return (0,)


async def _allow_captcha(*_args, **_kwargs):
    return 0


async def _empty_html(*_args, **_kwargs):
    return ""


async def _owner_account(*_args, **_kwargs):
    return 0


async def _error(_conn, code):
    return flask_module.make_response({"error": code}, 401)


def _run(handler: Callable):
    return anyio.run(handler)


class AuthFixture:
    def __init__(self, fixture: SecurityFixture) -> None:
        self.fixture = fixture
        self.riro_result = {
            "status": "success",
            "name": "Synthetic Student",
            "student_number": "1101",
            "generation": 40,
            "is_teacher": False,
        }
        with fixture.connect() as conn:
            conn.executescript(
                """
                create table user_set (id text, name text, data text);
                create table login_token (user_id text, token text, expires text);
                create table other (name text, data text);
                create table data (title text, data text);
                create table rb (block text, end text, why text, login text, ongoing text, today text);
                """
            )
        self.flask = FlaskFacade()
        auth_state = load_source_definitions(
            ROOT / "route/tool/auth_state.py",
            (
                "AUTH_PENDING_TTL",
                "LOGIN_STATE_KEYS",
                "REGISTRATION_PROOF_KEYS",
                "LOGOUT_STATE_KEYS",
                "set_auth_pending",
                "get_auth_pending",
                "auth_pending_matches",
                "_clear",
                "clear_login_state",
                "clear_registration_state",
                "clear_auth_transients",
                "clear_logout_state",
            ),
            {"time": time, "AuthPurpose": str, "SessionState": dict},
        )
        common = {
            "flask": self.flask,
            "get_db_connect": fixture.connect,
            "db_change": lambda query: query,
            "ip_check": lambda: "127.0.0.1",
            "ip_or_user": lambda _ip: 1,
            "ban_check": _allow_ban,
            "acl_check": _owner_account,
            "captcha_post": _allow_captcha,
            "captcha_get": _empty_html,
            "re_error": _error,
            "redirect": lambda _conn, path: flask_module.redirect(path),
            "pw_check": lambda _conn, supplied, stored, _encode, _user: int(supplied == stored),
            "ua_plus": lambda *_args: None,
            "get_time": lambda: "2026-09-22 12:00:00",
            "os": __import__("os"),
            "hashlib": __import__("hashlib"),
            "hmac": __import__("hmac"),
            "datetime": __import__("datetime"),
            "easy_minify": lambda _conn, value: value,
            "skin_check": lambda _conn: "synthetic",
            "get_lang": lambda _conn, key: key,
            "wiki_set": _allow_captcha,
            "wiki_custom": _allow_captcha,
            "wiki_css": lambda _value: "",
            "http_warning": lambda _conn: "",
        }
        common.update(auth_state.definitions)
        self.login = self._load("route/login_login.py", "login_login", common)
        self.login_2fa = self._load("route/login_login_2fa.py", "login_login_2fa", common)
        self.logout = self._load("route/login_logout.py", "login_logout", common)
        riro_dependencies = dict(common)
        riro_dependencies.update({
            "asyncio": __import__("asyncio"),
            "check_riro_login": lambda _user, _password: self.riro_result,
            "easy_minify": lambda _conn, value: value,
            "skin_check": lambda _conn: "synthetic",
            "get_lang": lambda _conn, key: key,
            "wiki_set": _allow_captcha,
            "wiki_custom": _allow_captcha,
            "wiki_css": lambda _value: "",
        })
        self.riro = self._load("route/riro_login_page.py", "riro_login_page", riro_dependencies)
        register_dependencies = dict(common)
        register_dependencies.update({
            "datetime": datetime,
            "hashlib": hashlib,
            "html": html,
            "hmac": __import__("hmac"),
            "re": re,
            "unicodedata": unicodedata,
            "_USERNAME_RE": re.compile(r"^[a-zA-Z0-9가-힣._@]+$"),
            "pw_encode": lambda _conn, password, _encode: password,
            "number_check": lambda value: value,
            "easy_minify": lambda _conn, value: value,
            "skin_check": lambda _conn: "synthetic",
            "get_lang": lambda _conn, key: key,
            "wiki_set": _allow_captcha,
            "wiki_custom": _allow_captcha,
            "wiki_css": lambda _value: "",
            "http_warning": lambda _conn: "",
            "ban_insert": lambda *_args, **_kwargs: None,
            "history_plus": lambda *_args, **_kwargs: None,
            "render_set": lambda *_args, **_kwargs: None,
        })
        register_helpers = load_source_definitions(
            ROOT / "route/login_register.py",
            ("_valid_date", "_norm", "_valid_user_id", "_valid_student_id", "_save_profile_extra", "add_user"),
            register_dependencies,
        )
        register_dependencies.update(register_helpers.definitions)
        self.register_student = self._load("route/login_register.py", "login_register_student", register_dependencies)
        self.register_teacher = self._load("route/login_register.py", "login_register_teacher", register_dependencies)
        self.traces: list[LoadedSource] = []
        fixture.app.add_url_rule("/login", "login", lambda: _run(self.login), methods=("GET", "POST"))
        fixture.app.add_url_rule("/login/2fa", "login_2fa", lambda: _run(self.login_2fa), methods=("GET", "POST"))
        fixture.app.add_url_rule("/logout", "logout", lambda: _run(self.logout), methods=("GET", "POST"))
        fixture.app.add_url_rule("/riro_login", "riro_login", lambda: _run(self.riro), methods=("GET", "POST"))
        fixture.app.add_url_rule("/register", "register", lambda: _run(self.riro), methods=("GET", "POST"))
        fixture.app.add_url_rule("/register_form_student", "register_student", lambda: _run(self.register_student), methods=("GET", "POST"))
        fixture.app.add_url_rule("/register_form_teacher", "register_teacher", lambda: _run(self.register_teacher), methods=("GET", "POST"))

    @staticmethod
    def _load(relative: str, name: str, dependencies: dict) -> Callable:
        loaded = load_source_definitions(ROOT / relative, (name,), dependencies)
        definition = loaded.definitions[name]
        if not callable(definition):
            raise SourceDefinitionError(f"{name} is not callable")
        return definition

    def add_user(self, user_id: str, password: str, *, two_factor: bool = False, linked: bool = True) -> None:
        rows = [
            (user_id, "user_name", user_id),
            (user_id, "pw", password),
            (user_id, "encode", "plain"),
            (user_id, "student_id", "1101" if linked else ""),
        ]
        if two_factor:
            rows.extend(((user_id, "2fa", "on"), (user_id, "2fa_pw", "factor"), (user_id, "2fa_pw_encode", "plain")))
        with self.fixture.connect() as conn:
            conn.executemany("insert into user_set values (?, ?, ?)", rows)


class AuthenticationBaselineTests(unittest.TestCase):
    def test_unconfigured_2fa_account_completes_primary_login(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("plain-user", "primary")
            client = fixture.app.test_client()

            response = client.post("/login", data={"id": "plain-user", "pw": "primary"})

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/user")
            with client.session_transaction() as session:
                self.assertEqual(session.get("id"), "plain-user")

    def test_configured_2fa_account_completes_only_after_factor(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()

            first = client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertEqual(session.get("login_id"), "factor-user")
            second = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(first.headers["Location"], "/login/2fa")
            self.assertEqual(second.headers["Location"], "/user")
            with client.session_transaction() as session:
                self.assertEqual(session.get("id"), "factor-user")

    def test_logout_preserves_display_preferences(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            client = fixture.app.test_client()
            with client.session_transaction() as session:
                session["id"] = "plain-user"
                session["skin"] = "dark"

            response = client.post("/logout")

            self.assertEqual(response.status_code, 302)
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertEqual(session.get("skin"), "dark")

    def test_unconfigured_2fa_auto_login_cookie_and_token_are_preserved(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("plain-user", "primary")
            client = fixture.app.test_client()

            response = client.post(
                "/login",
                data={"id": "plain-user", "pw": "primary", "auto_login": "on"},
            )

            self.assertIn("auto_login=", response.headers.get("Set-Cookie", ""))
            with fixture.connect() as conn:
                self.assertEqual(
                    conn.execute("select count(*) from login_token where user_id = ?", ("plain-user",)).fetchone()[0],
                    1,
                )


class AuthenticationSecurityTests(unittest.TestCase):
    def test_login_creates_account_bound_2fa_context_and_consumes_it(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()

            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with client.session_transaction() as session:
                pending = session.get("auth_pending")
                self.assertEqual(pending["purpose"], "login_2fa")
                self.assertEqual(pending["account_id"], "factor-user")
                self.assertIsInstance(pending["issued_at"], int)
            client.post("/login/2fa", data={"pw": "factor"})

            with client.session_transaction() as session:
                self.assertNotIn("auth_pending", session)
                self.assertNotIn("login_id", session)
                self.assertNotIn("b_id", session)

    def test_missing_factor_secret_denies_completion(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with fixture.connect() as conn:
                conn.execute("delete from user_set where id = ? and name = '2fa_pw'", ("factor-user",))

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.status_code, 401)
            with client.session_transaction() as session:
                self.assertNotIn("id", session)

    def test_disabled_2fa_during_pending_login_requires_primary_login(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with fixture.connect() as conn:
                conn.execute("update user_set set data = '' where id = ? and name = '2fa'", ("factor-user",))

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertNotIn("auth_pending", session)

    def test_cross_account_2fa_state_is_rejected(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("first", "primary", two_factor=True)
            auth.add_user("second", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "first", "pw": "primary"})
            with client.session_transaction() as session:
                session["login_id"] = "second"

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertNotIn("login_id", session)

    def test_expired_2fa_context_is_rejected(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with client.session_transaction() as session:
                pending = dict(session["auth_pending"])
                pending["issued_at"] = 1
                session["auth_pending"] = pending

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)

    def test_future_issued_2fa_context_is_rejected(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with client.session_transaction() as session:
                pending = dict(session["auth_pending"])
                pending["issued_at"] = int(time.time()) + 60
                session["auth_pending"] = pending

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertNotIn("auth_pending", session)

    def test_wrong_factor_preserves_original_issued_at(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with client.session_transaction() as session:
                issued_at = session["auth_pending"]["issued_at"]

            response = client.post("/login/2fa", data={"pw": "wrong-factor"})

            self.assertEqual(response.status_code, 401)
            with client.session_transaction() as session:
                self.assertEqual(session["auth_pending"]["issued_at"], issued_at)
                self.assertNotIn("id", session)

    def test_riro_login_with_2fa_waits_for_factor_and_keeps_retry_time(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("riro-user", "primary", two_factor=True, linked=False)
            client = fixture.app.test_client()
            first = client.post("/login", data={"id": "riro-user", "pw": "primary"})
            self.assertEqual(first.headers["Location"], "/riro_login")
            with client.session_transaction() as session:
                issued_at = session["auth_pending"]["issued_at"]
            auth.riro_result = {"status": "failure", "message": "denied"}
            denied = client.post("/riro_login", data={"riro_id": "x", "riro_pw": "y"})
            self.assertEqual(denied.status_code, 200)
            with fixture.connect() as conn:
                self.assertEqual(
                    conn.execute("select data from user_set where id = ? and name = 'student_id'", ("riro-user",)).fetchone()[0],
                    "",
                )
            with client.session_transaction() as session:
                self.assertEqual(session["auth_pending"]["issued_at"], issued_at)
                self.assertNotIn("id", session)
            auth.riro_result = {
                "status": "success",
                "name": "Synthetic Student",
                "student_number": "1101",
                "generation": 40,
                "is_teacher": False,
            }

            accepted = client.post("/riro_login", data={"riro_id": "x", "riro_pw": "y"})

            self.assertEqual(accepted.headers["Location"], "/login/2fa")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)
                self.assertEqual(session.get("login_id"), "riro-user")
                self.assertEqual(session["auth_pending"]["purpose"], "login_2fa")

    def test_riro_post_without_context_does_not_create_registration_proof(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            client = fixture.app.test_client()

            response = client.post("/riro_login", data={"riro_id": "x", "riro_pw": "y"})

            self.assertEqual(response.status_code, 302)
            with client.session_transaction() as session:
                self.assertNotIn("riro_verified", session)

    def test_logout_clears_auth_transients_and_preserves_preferences(self) -> None:
        with security_fixture() as fixture:
            AuthFixture(fixture)
            client = fixture.app.test_client()
            with client.session_transaction() as session:
                session.update({
                    "id": "factor-user",
                    "login_id": "factor-user",
                    "b_id": "factor-user",
                    "auth_pending": {"purpose": "login_2fa", "account_id": "factor-user", "issued_at": 1},
                    "riro_verified": True,
                    "c_key": "synthetic",
                    "skin": "dark",
                })

            client.post("/logout")

            with client.session_transaction() as session:
                self.assertEqual(session.get("skin"), "dark")
                for key in ("id", "login_id", "b_id", "auth_pending", "riro_verified", "c_key"):
                    self.assertNotIn(key, session)
            retry = client.post("/login/2fa", data={"pw": "factor"})
            self.assertEqual(retry.headers["Location"], "/login")

    def test_missing_factor_encode_denies_completion(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            client.post("/login", data={"id": "factor-user", "pw": "primary"})
            with fixture.connect() as conn:
                conn.execute("delete from user_set where id = ? and name = '2fa_pw_encode'", ("factor-user",))

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.status_code, 401)
            with client.session_transaction() as session:
                self.assertNotIn("id", session)

    def test_register_entry_clears_login_state_and_primary_login_clears_registration_proof(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("plain-user", "primary")
            client = fixture.app.test_client()
            with client.session_transaction() as session:
                session["login_id"] = "plain-user"
                session["auth_pending"] = {"purpose": "login_2fa", "account_id": "plain-user", "issued_at": int(time.time())}

            client.get("/register")
            with client.session_transaction() as session:
                self.assertNotIn("login_id", session)
                self.assertEqual(session["auth_pending"]["purpose"], "register_riro")
            client.post("/register", data={"riro_id": "x", "riro_pw": "y"})
            client.post("/login", data={"id": "plain-user", "pw": "primary"})

            with client.session_transaction() as session:
                self.assertEqual(session.get("id"), "plain-user")
                self.assertNotIn("riro_verified", session)
                self.assertNotIn("auth_pending", session)

    def test_registration_success_consumes_student_and_teacher_proof(self) -> None:
        cases = (
            ("/register_form_student", "Student Name", "1101", 40, "studentaccount"),
            ("/register_form_teacher", "Teacher Name", "0", 0, "teacheraccount"),
        )
        for path, name, student_number, generation, account in cases:
            with self.subTest(path=path), security_fixture() as fixture:
                AuthFixture(fixture)
                client = fixture.app.test_client()
                with client.session_transaction() as session:
                    session.update({
                        "riro_verified": True,
                        "riro_name": name,
                        "riro_student_number": student_number,
                        "riro_generation": generation,
                        "auth_pending": {"purpose": "register_verified", "account_id": None, "issued_at": int(time.time())},
                    })

                response = client.post(path, data={
                    "birth_year": "2000",
                    "birth_month": "1",
                    "birth_day": "1",
                    "gender": "female",
                    "user_name": account,
                    "pw": "password",
                    "pw2": "password",
                    "agreement": "agree",
                })

                self.assertEqual(response.status_code, 200)
                with client.session_transaction() as session:
                    for key in ("auth_pending", "riro_verified", "riro_name", "riro_student_number", "riro_generation"):
                        self.assertNotIn(key, session)
                with fixture.connect() as conn:
                    self.assertEqual(conn.execute("select count(*) from user_set where id = ? and name = 'pw'", (account,)).fetchone()[0], 2)

    def test_registration_proof_cannot_complete_login_factor(self) -> None:
        with security_fixture() as fixture:
            auth = AuthFixture(fixture)
            auth.add_user("factor-user", "primary", two_factor=True)
            client = fixture.app.test_client()
            with client.session_transaction() as session:
                session["login_id"] = "factor-user"
                session["auth_pending"] = {"purpose": "register_verified", "account_id": None, "issued_at": int(time.time())}

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("id", session)

    def test_empty_factor_values_and_malformed_pending_state_are_rejected(self) -> None:
        for factor_name in ("2fa_pw", "2fa_pw_encode"):
            with self.subTest(factor_name=factor_name), security_fixture() as fixture:
                auth = AuthFixture(fixture)
                auth.add_user("factor-user", "primary", two_factor=True)
                client = fixture.app.test_client()
                client.post("/login", data={"id": "factor-user", "pw": "primary"})
                with fixture.connect() as conn:
                    conn.execute("update user_set set data = '' where id = ? and name = ?", ("factor-user", factor_name))

                response = client.post("/login/2fa", data={"pw": "factor"})

                self.assertEqual(response.status_code, 401)
                with client.session_transaction() as session:
                    self.assertNotIn("id", session)
        with security_fixture() as fixture:
            AuthFixture(fixture)
            client = fixture.app.test_client()
            with client.session_transaction() as session:
                session["login_id"] = "factor-user"
                session["auth_pending"] = {"purpose": "login_2fa", "account_id": ["factor-user"], "issued_at": "now"}

            response = client.post("/login/2fa", data={"pw": "factor"})

            self.assertEqual(response.headers["Location"], "/login")
            with client.session_transaction() as session:
                self.assertNotIn("login_id", session)


def serve_manual(host: str, port: int) -> None:
    with security_fixture() as fixture:
        auth = AuthFixture(fixture)
        auth.add_user("factor-user", "primary", two_factor=True)
        auth.add_user("plain-user", "primary")
        auth.add_user("riro-user", "primary", two_factor=True, linked=False)

        @fixture.app.get("/user")
        def fixture_user():
            return {"id": flask_module.session.get("id")}

        @fixture.app.get("/__fixture/session")
        def fixture_session():
            pending = flask_module.session.get("auth_pending")
            return {
                "id": flask_module.session.get("id"),
                "login_id": flask_module.session.get("login_id"),
                "pending_purpose": pending.get("purpose") if isinstance(pending, dict) else None,
                "riro_verified": bool(flask_module.session.get("riro_verified")),
            }

        @fixture.app.get("/__fixture/user/<user_id>")
        def fixture_profile(user_id: str):
            with fixture.connect() as conn:
                rows = conn.execute(
                    "select name, data from user_set where id = ? and name in ('student_id', 'real_name', 'generation')",
                    (user_id,),
                ).fetchall()
            return dict(rows)

        server = make_server(host, port, fixture.app)
        print(json.dumps({"host": host, "port": server.server_port}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--serve":
        serve_manual(sys.argv[2], int(sys.argv[3]))
    else:
        unittest.main()
