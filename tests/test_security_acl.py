from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
import socket
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
import flask

from security_support import load_source_definitions


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "route" / "tool" / "func.py"


class FastSleep:
    async def sleep(self, _seconds: float) -> None:
        return None


class FastTimeoutAiohttp:
    timeout_errors = 0

    @classmethod
    def ClientSession(cls, *, timeout: aiohttp.ClientTimeout) -> aiohttp.ClientSession:
        trace = aiohttp.TraceConfig()

        async def record_timeout(_session, _context, params) -> None:
            if isinstance(params.exception, asyncio.TimeoutError):
                cls.timeout_errors += 1

        trace.on_request_exception.append(record_timeout)
        return aiohttp.ClientSession(timeout=timeout, trace_configs=[trace])

    @staticmethod
    def ClientTimeout(*, total: float) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=0.2)


class AclBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.requests: list[str] = []
        self.handler_errors: list[str] = []
        self.handler_started = asyncio.Event()
        self.handler_finished = asyncio.Event()
        self.delay = 0.0
        self.responses: dict[str, tuple[int, str, str]] = {
            "api_func_acl": (200, '{"response":"ok","data":true}', "application/json"),
            "api_func_auth_post": (200, '{"response":"ok","data":true}', "application/json"),
            "api_list_acl": (200, '{"response":"ok","data":["synthetic"]}', "application/json"),
        }
        app = web.Application()
        app.router.add_post("/", self.bridge)
        self.server = TestServer(app, host="localhost")
        await self.server.start_server()
        loaded = load_source_definitions(
            SOURCE,
            ("python_to_golang", "acl_check"),
            {
                "aiohttp": aiohttp,
                "asyncio": FastSleep(),
                "datetime": datetime,
                "flask": flask,
                "global_some_set_do": self.setting,
                "ip_check": lambda: "127.0.0.1",
                "json_dumps": json.dumps,
                "release_expired_bans": lambda: None,
            },
        )
        self.python_to_golang = loaded.definitions["python_to_golang"]
        self.acl_check = loaded.definitions["acl_check"]

    async def asyncTearDown(self) -> None:
        await self.server.close()

    def setting(self, name: str) -> str:
        return str(self.server.port) if name == "golang_port" else ""

    async def bridge(self, request: web.Request) -> web.Response:
        payload = json.loads(await request.text())
        route = payload["url"]
        self.requests.append(route)
        status, body, content_type = self.responses[route]
        try:
            if self.delay:
                self.handler_started.set()
                await asyncio.sleep(self.delay)
            return web.Response(status=status, text=body, content_type=content_type)
        except Exception as error:
            self.handler_errors.append(type(error).__name__)
            raise
        finally:
            if self.delay:
                self.handler_finished.set()

    async def test_allows_true_and_records_memo(self) -> None:
        result = await self.acl_check(memo="synthetic permission")

        self.assertEqual(result, 0)
        self.assertEqual(self.requests, ["api_func_acl", "api_func_auth_post"])

    async def test_denies_false_without_recording_memo(self) -> None:
        self.responses["api_func_acl"] = (200, '{"response":"ok","data":false}', "application/json")

        result = await self.acl_check(memo="synthetic permission")

        self.assertEqual(result, 1)
        self.assertEqual(self.requests, ["api_func_acl"])

    async def test_keeps_other_api_normal_response(self) -> None:
        result = await self.python_to_golang("api_list_acl")

        self.assertEqual(result, {"response": "ok", "data": ["synthetic"]})
        self.assertEqual(self.requests, ["api_list_acl"])

    async def test_keeps_http_status_handling_for_other_apis(self) -> None:
        self.responses["api_list_acl"] = (500, '{"response":"ok","data":["synthetic"]}', "application/json")

        result = await self.python_to_golang("api_list_acl")

        self.assertEqual(result, {"response": "ok", "data": ["synthetic"]})
        self.assertEqual(self.requests, ["api_list_acl"])

    async def test_denies_invalid_acl_responses_without_recording_memo(self) -> None:
        cases = (
            ("error_string", 200, '{"response":"error","data":"failed"}', "application/json"),
            ("null", 200, "null", "application/json"),
            ("empty", 200, "", "application/json"),
            ("missing_response", 200, '{"data":true}', "application/json"),
            ("missing", 200, '{"response":"ok"}', "application/json"),
            ("wrong_type", 200, '{"response":"ok","data":1}', "application/json"),
            ("string_true", 200, '{"response":"ok","data":"true"}', "application/json"),
            ("non_json", 200, "not json", "text/plain"),
            ("http_500", 500, '{"response":"ok","data":true}', "application/json"),
        )
        for name, status, body, content_type in cases:
            with self.subTest(name=name):
                self.requests.clear()
                self.responses["api_func_acl"] = (status, body, content_type)

                result = await self.acl_check(memo="synthetic permission")

                self.assertEqual(result, 1)
                self.assertNotIn("api_func_auth_post", self.requests)
                if name == "http_500":
                    self.assertEqual(self.requests, ["api_func_acl"])
                else:
                    self.assertTrue(self.requests)

    async def test_denies_timeout_without_recording_memo(self) -> None:
        self.delay = 0.5
        FastTimeoutAiohttp.timeout_errors = 0
        source_globals = self.python_to_golang.__globals__
        original_aiohttp = source_globals["aiohttp"]
        source_globals["aiohttp"] = FastTimeoutAiohttp
        try:
            result_task = asyncio.create_task(self.acl_check(memo="synthetic permission"))
            await asyncio.wait_for(self.handler_started.wait(), timeout=2)
            result = await result_task
        finally:
            source_globals["aiohttp"] = original_aiohttp

        await asyncio.wait_for(self.handler_finished.wait(), timeout=2)

        self.assertEqual(result, 1)
        self.assertIs(source_globals["aiohttp"], original_aiohttp)
        self.assertEqual(self.handler_errors, [])
        self.assertGreater(FastTimeoutAiohttp.timeout_errors, 0)
        self.assertNotIn("api_func_auth_post", self.requests)

    async def test_denies_refused_connection_without_recording_memo(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        source_globals = self.python_to_golang.__globals__
        original_setting = source_globals["global_some_set_do"]
        source_globals["global_some_set_do"] = lambda _name: str(port)
        try:
            result = await self.acl_check(memo="synthetic permission")
        finally:
            source_globals["global_some_set_do"] = original_setting

        self.assertEqual(result, 1)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
