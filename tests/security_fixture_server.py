# /// script
# requires-python = ">=3.11"
# dependencies = ["flask>=3.1"]
# ///
"""Side-effect-free AST loader and isolated HTTP/SQLite security fixture.

# ─── How to run ───
# python -B tests/security_fixture_server.py --self-check
# python -B tests/security_fixture_server.py --serve --host 127.0.0.1 --port 8767
"""

from __future__ import annotations

import argparse
import builtins
from collections.abc import Callable, Iterator
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from typing import ContextManager, Final, NoReturn

from flask import Flask, jsonify
from werkzeug.serving import make_server

from security_support import (
    FixtureBoundaryError,
    LoadedSource,
    SourceTrace,
    load_source_definitions,
    side_effect_guard,
)


ROOT: Final = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class SecurityFixture:
    app: Flask
    root: Path
    database: Path
    connect: Callable[[], ContextManager[sqlite3.Connection]]
    source_traces: tuple[SourceTrace, ...]

    def path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise FixtureBoundaryError(f"outside fixture root: {relative}")
        return candidate

    def external_request(self, url: str) -> NoReturn:
        raise FixtureBoundaryError(f"external request denied: {url}")


@contextmanager
def security_fixture(
    register: Callable[[SecurityFixture], None] | None = None,
) -> Iterator[SecurityFixture]:
    """Yield a loopback-ready app backed only by a temporary synthetic database."""
    with TemporaryDirectory(prefix="wiki-security-") as directory:
        root = Path(directory).resolve()
        database = root / "fixture.db"
        settings = {"db_type": "sqlite", "db_name": str(database.with_suffix(""))}
        loaded = load_source_definitions(
            ROOT / "route" / "tool" / "func.py",
            ("get_db_connect",),
            {"sqlite3": sqlite3, "global_some_set_do": settings.__getitem__},
        )
        db_connect = loaded.definitions["get_db_connect"]
        if not isinstance(db_connect, type):
            raise FixtureBoundaryError("get_db_connect is not a class")

        def connect() -> ContextManager[sqlite3.Connection]:
            return db_connect()

        with connect() as conn:
            conn.execute("create table synthetic_user (id text primary key, display_name text not null)")
            conn.execute("insert into synthetic_user values (?, ?)", ("synthetic-1", "Fixture User"))

        app = Flask(__name__)
        app.secret_key = "synthetic-fixture-only"
        fixture = SecurityFixture(app, root, database, connect, (loaded.trace,))
        if register is not None:
            register(fixture)
        yield fixture


def _register_self_check(fixture: SecurityFixture) -> None:
    @fixture.app.get("/synthetic/<user_id>")
    def synthetic_user(user_id: str):
        with fixture.connect() as conn:
            row = conn.execute(
                "select id, display_name from synthetic_user where id = ?", (user_id,),
            ).fetchone()
        return jsonify({"id": row[0], "display_name": row[1]}) if row else (jsonify({"error": "missing"}), 404)

    @fixture.app.get("/external")
    def external():
        try:
            fixture.external_request("https://example.invalid")
        except FixtureBoundaryError:
            return jsonify({"error": "external_denied"}), 503


def self_check() -> None:
    with security_fixture(_register_self_check) as fixture:
        client = fixture.app.test_client()
        response = client.get("/synthetic/synthetic-1")
        assert response.status_code == 200
        assert response.get_json() == {"display_name": "Fixture User", "id": "synthetic-1"}
        assert client.get("/external").status_code == 503
        assert fixture.path("inside.txt").parent == fixture.root
        path_rejected = False
        try:
            fixture.path("../outside.txt")
        except FixtureBoundaryError:
            path_rejected = True
        if not path_rejected:
            raise AssertionError("path traversal was accepted")
        source_rejected = False
        try:
            load_source_definitions(Path(os.environ.get("SystemRoot", "C:/Windows")) / "win.ini", ("x",), {})
        except FixtureBoundaryError:
            source_rejected = True
        if not source_rejected:
            raise AssertionError("outside source was accepted")
        with fixture.connect() as conn:
            assert conn.isolation_level is None
            conn.execute("insert into synthetic_user values (?, ?)", ("autocommit", "Committed"))
        with fixture.connect() as conn:
            assert conn.execute("select display_name from synthetic_user where id = ?", ("autocommit",)).fetchone() == ("Committed",)
        with side_effect_guard() as guard_denials:
            probes = (
                lambda: builtins.open(fixture.path("blocked.txt"), "w"),
                socket.socket,
                lambda: subprocess.Popen(("never-run",)),
                lambda: builtins.__import__("pip"),
            )
            denied = 0
            for probe in probes:
                try:
                    probe()
                except FixtureBoundaryError:
                    denied += 1
            assert denied == len(probes)
        assert guard_denials == Counter({"write": 1, "network": 1, "subprocess": 1, "pip": 1})
        print(json.dumps({
            "result": "PASS",
            "database": str(fixture.database),
            "synthetic_user": "synthetic-1",
            "source_traces": [{
                "path": trace.path,
                "sha256": trace.sha256,
                "definitions": trace.definitions,
                "loader_guard_calls": dict(trace.loader_guard_calls),
            } for trace in fixture.source_traces],
            "negative_control_denials": dict(guard_denials),
        }, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--serve", action="store_true")
    parser.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return 0
    with security_fixture(_register_self_check) as fixture:
        server = make_server(args.host, args.port, fixture.app)
        print(json.dumps({"host": args.host, "port": server.server_port, "pid": os.getpid()}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return 0
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
