"""Exercise production request limits without app.py's DB/Go startup side effects."""

import ast
from contextlib import closing
from pathlib import Path
import unittest

from flask import Flask, request
from werkzeug.test import EnvironBuilder


def build_test_app() -> Flask:
    app = Flask(__name__)
    source = Path(__file__).resolve().parents[1] / "app.py"
    # Execute the actual limit assignments so removing the fix breaks this test.
    assignments = [
        node for node in ast.walk(ast.parse(source.read_text(encoding="utf8")))
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]).startswith("app.config['MAX_")
    ]
    config = ast.Module(body=assignments, type_ignores=[])
    exec(compile(config, str(source), "exec"), {"app": app})

    @app.post("/edit/test")
    def edit() -> str:
        return request.form["content"]

    return app


class FormLimitsTest(unittest.TestCase):
    def test_long_korean_edit_round_trips(self) -> None:
        client = build_test_app().test_client()
        for count in (60_000, 100_000):
            with self.subTest(characters=count):
                content = "가" * count
                response = client.post("/edit/test", data={
                    "content": content, "doc_data_org": content, "ver": "1",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_data(as_text=True), content)

    def test_large_multipart_text_round_trips(self) -> None:
        content = "가" * 200_000
        with closing(EnvironBuilder(
            "/edit/test", method="POST", data={"content": content},
            content_type="multipart/form-data",
        )) as builder:
            response = build_test_app().test_client().open(builder.get_environ())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), content)

    def test_total_request_limit_still_rejects_oversized_forms(self) -> None:
        app = build_test_app()
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 16_000_000)
        response = app.test_client().post(
            "/edit/test", data={"content": "x" * 16_000_000},
        )
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
