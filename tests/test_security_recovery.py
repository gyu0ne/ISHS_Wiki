from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import string
import sys
from types import SimpleNamespace
import unittest

import anyio
from flask import make_response, request
from werkzeug.serving import make_server

from security_fixture_server import ROOT, load_source_definitions, security_fixture


RECOVERY_NAMES = (
    "_RECOVERY_ALPHABET", "_SUPPORTED_ENCODINGS", "_begin_transaction",
    "_new_secret", "_recover_with_key", "login_find_key",
)
SETTING_NAMES = (
    "_RECOVERY_ALPHABET", "_begin_key_transaction", "_new_recovery_key",
    "_replace_recovery_key",
)


def _db_change(db_type: str):
    return load_source_definitions(
        ROOT / "route" / "tool" / "func_tool.py", ("db_change",),
        {"global_func_some_set_do": lambda name: db_type if name == "db_type" else None},
    ).definitions["db_change"]


def _load_password_functions(db_type: str = "sqlite"):
    return load_source_definitions(
        ROOT / "route" / "tool" / "func.py", ("pw_encode", "pw_check"),
        {"db_change": _db_change(db_type), "hashlib": hashlib},
    ).definitions


def _load_recovery(db_type: str = "sqlite"):
    return load_source_definitions(
        ROOT / "route" / "login_find_key.py", RECOVERY_NAMES,
        {
            "db_change": _db_change(db_type),
            "global_some_set_do": lambda name: db_type if name == "db_type" else None,
            "pw_encode": _load_password_functions(db_type)["pw_encode"],
            "secrets": secrets,
        },
    )


def _load_key_setting(db_type: str = "sqlite"):
    return load_source_definitions(
        ROOT / "route" / "user_setting_key.py", SETTING_NAMES,
        {
            "db_change": lambda sql: sql,
            "global_some_set_do": lambda name: db_type if name == "db_type" else None,
            "secrets": secrets,
        },
    )


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("create table user_set (name text, id text, data text)")
    conn.execute("create table other (name text, data text)")
    conn.executemany(
        "insert into other values (?, ?)",
        (("encode", "sha3"), ("salt_key", "synthetic-salt"), ("reset_user_text", "")),
    )


def _insert_account(
    conn: sqlite3.Connection, *, user_id: str = "alice",
    recovery_key: str = "R" * 128, encodings: tuple[str, ...] = ("sha3",),
    passwords: int = 1, two_factor: str = "on",
) -> None:
    password = _load_password_functions()["pw_encode"]
    for encoding in encodings:
        conn.execute("insert into user_set values ('encode', ?, ?)", (user_id, encoding))
    hash_encoding = (encodings[0] if encodings else "sha3") or "sha3"
    for _index in range(passwords):
        conn.execute(
            "insert into user_set values ('pw', ?, ?)",
            (user_id, password(conn, "old-password", hash_encoding)),
        )
    conn.execute("insert into user_set values ('random_key', ?, ?)", (user_id, recovery_key))
    conn.execute("insert into user_set values ('2fa', ?, ?)", (user_id, two_factor))
    conn.execute("insert into user_set values ('2fa_pw', ?, 'factor-secret')", (user_id,))
    conn.execute("insert into user_set values ('2fa_pw_encode', ?, 'sha3')", (user_id,))


def register_recovery_surface(fixture) -> None:
    with fixture.connect() as conn:
        _create_schema(conn)
        _insert_account(conn)
    flask_boundary = SimpleNamespace(
        request=request, make_response=make_response,
        render_template=lambda *_args, **kwargs: kwargs["data"],
    )

    async def captcha_post(_conn, _response):
        return 0

    async def empty_async():
        return ""

    loaded = load_source_definitions(
        ROOT / "route" / "login_find_key.py", RECOVERY_NAMES,
        {
            "get_db_connect": fixture.connect,
            "flask": flask_boundary,
            "captcha_post": captcha_post,
            "redirect": lambda _conn, path: ("", 302, {"Location": path}),
            "db_change": lambda sql: sql,
            "global_some_set_do": lambda name: "sqlite" if name == "db_type" else None,
            "pw_encode": _load_password_functions()["pw_encode"],
            "secrets": secrets,
            "easy_minify": lambda _conn, data: data,
            "skin_check": lambda _conn: "unused",
            "get_lang": lambda _conn, key: key,
            "wiki_set": empty_async,
            "wiki_custom": lambda _conn: empty_async(),
            "wiki_css": lambda _value: "",
            "re_error": lambda *_args: empty_async(),
        },
    )
    handler = loaded.definitions["login_find_key"]

    @fixture.app.post("/login/find/key")
    def recover():
        return anyio.run(handler)


class _FaultCursor:
    def __init__(self, cursor: sqlite3.Cursor, fail_after: str) -> None:
        self._cursor = cursor
        self._fail_after = fail_after
        self.rowcount = -1

    def execute(self, sql, parameters=()):
        result = self._cursor.execute(sql, parameters)
        self.rowcount = self._cursor.rowcount
        normalized = " ".join(sql.lower().split())
        failed = (
            self._fail_after == "delete" and "delete from user_set" in normalized
            or self._fail_after == "password" and "update user_set set data =" in normalized and "pw" in normalized
            or self._fail_after == "2fa" and "update user_set set data = ''" in normalized and "2fa" in normalized
        )
        if failed:
            raise sqlite3.OperationalError(f"synthetic failure after {self._fail_after}")
        return result

    def fetchall(self):
        return self._cursor.fetchall()


class _FaultConnection:
    def __init__(self, conn: sqlite3.Connection, fail_after: str) -> None:
        self._conn = conn
        self._fail_after = fail_after

    def cursor(self):
        return _FaultCursor(self._conn.cursor(), self._fail_after)

    def execute(self, sql, parameters=()):
        return self._conn.execute(sql, parameters)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def begin(self) -> None:
        self._conn.begin()


class RecoveryTest(unittest.TestCase):
    def test_valid_key_preserves_supported_encoding_and_duplicate_rows(self) -> None:
        password = _load_password_functions()
        for encoding in ("sha256", "sha3", "sha3-512", "sha3-salt", "sha3-512-salt"):
            with self.subTest(encoding=encoding), security_fixture() as fixture:
                with fixture.connect() as conn:
                    _create_schema(conn)
                    _insert_account(conn, encodings=(encoding, encoding), passwords=2)
                    conn.execute(
                        "update user_set set data = 'different-legacy-hash' "
                        "where rowid = (select min(rowid) from user_set where name = 'pw')"
                    )
                    recovered = _load_recovery().definitions["_recover_with_key"](
                        conn, "R" * 128, "new-password",
                    )
                    self.assertEqual(recovered, "alice")
                    rows = conn.execute(
                        "select data from user_set where id = 'alice' and name = 'pw'",
                    ).fetchall()
                    self.assertEqual(len(rows), 2)
                    self.assertTrue(all(
                        password["pw_check"](conn, "new-password", row[0], encoding, "") == 1
                        for row in rows
                    ))

    def test_first_use_succeeds_and_second_use_changes_nothing(self) -> None:
        with security_fixture() as fixture:
            with fixture.connect() as conn:
                _create_schema(conn)
                _insert_account(conn)
                recover = _load_recovery().definitions["_recover_with_key"]
                self.assertEqual(recover(conn, "R" * 128, "first-password"), "alice")
                state = conn.execute(
                    "select name, data from user_set where id = 'alice' order by rowid",
                ).fetchall()
                self.assertIsNone(recover(conn, "R" * 128, "second-password"))
                self.assertEqual(conn.execute(
                    "select name, data from user_set where id = 'alice' order by rowid",
                ).fetchall(), state)

    def test_two_concurrent_uses_have_exactly_one_winner(self) -> None:
        with security_fixture() as fixture:
            with fixture.connect() as conn:
                _create_schema(conn)
                _insert_account(conn)
            recover = _load_recovery().definitions["_recover_with_key"]

            def attempt(password: str):
                with fixture.connect() as conn:
                    return recover(conn, "R" * 128, password)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = tuple(pool.map(attempt, ("password-a", "password-b")))
            self.assertEqual(sum(result == "alice" for result in results), 1)
            self.assertEqual(sum(result is None for result in results), 1)

    def test_each_failure_point_rolls_back_key_password_and_2fa(self) -> None:
        for fail_after in ("delete", "password", "2fa"):
            with self.subTest(fail_after=fail_after), security_fixture() as fixture:
                with fixture.connect() as conn:
                    _create_schema(conn)
                    _insert_account(conn)
                    before = conn.execute(
                        "select name, data from user_set where id = 'alice' order by rowid",
                    ).fetchall()
                    with self.assertRaises(sqlite3.OperationalError):
                        _load_recovery().definitions["_recover_with_key"](
                            _FaultConnection(conn, fail_after), "R" * 128, "new-password",
                        )
                    self.assertEqual(conn.execute(
                        "select name, data from user_set where id = 'alice' order by rowid",
                    ).fetchall(), before)

    def test_ambiguous_or_invalid_account_does_not_consume_key(self) -> None:
        cases = (
            ((), 1, False), (("sha3", "sha256"), 1, False),
            (("unsupported",), 1, False), (("", "sha3"), 1, True),
            (("sha3",), 0, False),
        )
        for encodings, passwords, succeeds in cases:
            with self.subTest(encodings=encodings, passwords=passwords), security_fixture() as fixture:
                with fixture.connect() as conn:
                    _create_schema(conn)
                    _insert_account(conn, encodings=encodings, passwords=passwords)
                    result = _load_recovery().definitions["_recover_with_key"](
                        conn, "R" * 128, "new-password",
                    )
                    self.assertEqual(result == "alice", succeeds)
                    self.assertEqual(conn.execute(
                        "select count(*) from user_set where data = ? and name = 'random_key'",
                        ("R" * 128,),
                    ).fetchone(), (0 if succeeds else 1,))

    def test_duplicate_random_key_is_rejected_without_consumption(self) -> None:
        with security_fixture() as fixture:
            with fixture.connect() as conn:
                _create_schema(conn)
                _insert_account(conn)
                _insert_account(conn, user_id="bob")
                result = _load_recovery().definitions["_recover_with_key"](
                    conn, "R" * 128, "new-password",
                )
                self.assertIsNone(result)
                self.assertEqual(conn.execute(
                    "select count(*) from user_set where data = ? and name = 'random_key'",
                    ("R" * 128,),
                ).fetchone(), (2,))

    def test_empty_input_is_rejected_before_transaction(self) -> None:
        class NoTransaction:
            def cursor(self):
                raise AssertionError("empty input touched the database")

        self.assertIsNone(_load_recovery().definitions["_recover_with_key"](
            NoTransaction(), "", "new-password",
        ))

    def test_recovery_clears_only_enabled_2fa_and_keeps_factor_secrets(self) -> None:
        with security_fixture() as fixture:
            with fixture.connect() as conn:
                _create_schema(conn)
                _insert_account(conn)
                _load_recovery().definitions["_recover_with_key"](
                    conn, "R" * 128, "new-password",
                )
                self.assertEqual(conn.execute(
                    "select name, data from user_set where id = 'alice' and name like '2fa%' order by name",
                ).fetchall(), [("2fa", ""), ("2fa_pw", "factor-secret"), ("2fa_pw_encode", "sha3")])

    def test_new_secrets_use_existing_lengths_and_alphabet(self) -> None:
        new_secret = _load_recovery().definitions["_new_secret"]
        alphabet = set(string.ascii_letters + string.digits)
        for length in (32, 128):
            generated = new_secret(length)
            self.assertEqual(len(generated), length)
            self.assertLessEqual(set(generated), alphabet)

    def test_reissue_replaces_old_key_and_new_key_recovers(self) -> None:
        with security_fixture() as fixture:
            with fixture.connect() as conn:
                _create_schema(conn)
                _insert_account(conn)
                setting = _load_key_setting().definitions
                new_key = setting["_new_recovery_key"]()
                setting["_replace_recovery_key"](conn, "alice", new_key)
                self.assertEqual(len(new_key), 128)
                self.assertIsNone(_load_recovery().definitions["_recover_with_key"](
                    conn, "R" * 128, "rejected-password",
                ))
                self.assertEqual(_load_recovery().definitions["_recover_with_key"](
                    conn, new_key, "accepted-password",
                ), "alice")

    def test_http_surface_is_no_store_and_hides_submitted_key(self) -> None:
        with security_fixture(register_recovery_surface) as fixture:
            response = fixture.app.test_client().post(
                "/login/find/key", data={"key": "R" * 128},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertNotIn("R" * 128, response.get_data(as_text=True))


@unittest.skipUnless(os.getenv("TEST_MYSQL_DATABASE"), "real MySQL test database not configured")
class MySQLRecoveryTest(unittest.TestCase):
    def test_real_mysql_atomic_recovery(self) -> None:
        import pymysql

        config = json.loads(Path(os.environ["TEST_MYSQL_CONFIG"]).read_text(encoding="utf8"))

        def connect():
            return pymysql.connect(
                host=config["host"], port=int(config["port"]), user=config["user"],
                password=config["password"], database=config["database"],
                charset="utf8mb4", autocommit=True,
            )

        recover = _load_recovery("mysql").definitions["_recover_with_key"]
        conn = connect()
        try:
            with conn.cursor() as curs:
                curs.execute("drop table if exists user_set")
                curs.execute("drop table if exists other")
                curs.execute("create table user_set (name text, id text, data text) engine=InnoDB")
                curs.execute("create table other (name text, data text) engine=InnoDB")
                curs.executemany("insert into other values (%s, %s)", (
                    ("encode", "sha3"), ("salt_key", "synthetic-salt"),
                    ("reset_user_text", ""),
                ))
                curs.executemany("insert into user_set values (%s, %s, %s)", (
                    ("random_key", "mysql-user", "M" * 128),
                    ("pw", "mysql-user", "old-hash"),
                    ("pw", "mysql-user", "different-old-hash"),
                    ("encode", "mysql-user", "sha3"),
                    ("encode", "mysql-user", ""),
                    ("2fa", "mysql-user", "on"),
                ))
                curs.execute("show table status like 'user_set'")
                self.assertEqual(curs.fetchone()[1], "InnoDB")
            self.assertEqual(recover(conn, "M" * 128, "mysql-password"), "mysql-user")
            self.assertIsNone(recover(conn, "M" * 128, "second-password"))

            with conn.cursor() as curs:
                curs.execute("insert into user_set values (%s, %s, %s)", ("random_key", "mysql-user", "C" * 128))

            def attempt(password: str):
                attempt_conn = connect()
                try:
                    return recover(attempt_conn, "C" * 128, password)
                finally:
                    attempt_conn.close()

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = tuple(pool.map(attempt, ("mysql-a", "mysql-b")))
            self.assertEqual(sum(result == "mysql-user" for result in results), 1)
            self.assertEqual(sum(result is None for result in results), 1)

            for fail_after in ("delete", "password", "2fa"):
                with self.subTest(fail_after=fail_after), conn.cursor() as curs:
                    curs.execute("delete from user_set where name = 'random_key' and id = 'mysql-user'")
                    curs.execute("insert into user_set values (%s, %s, %s)", ("random_key", "mysql-user", "F" * 128))
                    curs.execute("update user_set set data = 'on' where name = '2fa' and id = 'mysql-user'")
                    curs.execute("select name, data from user_set where id = 'mysql-user' order by name, data")
                    before = curs.fetchall()
                with self.assertRaises(sqlite3.OperationalError):
                    recover(_FaultConnection(conn, fail_after), "F" * 128, "rollback-password")
                with conn.cursor() as curs:
                    curs.execute("select name, data from user_set where id = 'mysql-user' order by name, data")
                    self.assertEqual(curs.fetchall(), before)
        finally:
            with conn.cursor() as curs:
                curs.execute("drop table if exists user_set")
                curs.execute("drop table if exists other")
            conn.close()


def observe_recovery_data() -> None:
    with security_fixture() as fixture:
        with fixture.connect() as conn:
            _create_schema(conn)
            _insert_account(conn)
            recover = _load_recovery().definitions["_recover_with_key"]
            first = recover(conn, "R" * 128, "synthetic-password")
            second = recover(conn, "R" * 128, "unused-password")
            print(json.dumps({
                "first_use": first == "alice",
                "second_use_rejected": second is None,
                "remaining_keys": conn.execute(
                    "select count(*) from user_set where name = 'random_key'",
                ).fetchone()[0],
                "password_rows": conn.execute(
                    "select count(*) from user_set where name = 'pw' and id = 'alice'",
                ).fetchone()[0],
                "two_factor_enabled": conn.execute(
                    "select data from user_set where name = '2fa' and id = 'alice'",
                ).fetchone()[0] != "",
                "factor_secrets_retained": conn.execute(
                    "select count(*) from user_set where name in ('2fa_pw', '2fa_pw_encode') and id = 'alice'",
                ).fetchone()[0],
            }, sort_keys=True))


if __name__ == "__main__":
    if "--observe" in sys.argv:
        observe_recovery_data()
    elif "--serve" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--serve", action="store_true")
        parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
        parser.add_argument("--port", type=int, default=0)
        args = parser.parse_args()
        with security_fixture(register_recovery_surface) as fixture:
            server = make_server(args.host, args.port, fixture.app)
            print(json.dumps({"host": args.host, "port": server.server_port}), flush=True)
            try:
                server.serve_forever()
            finally:
                server.server_close()
    else:
        unittest.main()
