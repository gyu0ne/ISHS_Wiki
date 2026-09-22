"""Exercise production request limits without app.py's DB/Go startup side effects."""

import ast
from pathlib import Path
import unittest

import flask
from flask import Flask, request
from werkzeug.routing import PathConverter


def build_test_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "form-limit-test"
    app.url_map.converters['everything'] = PathConverter
    source = Path(__file__).resolve().parents[1] / "app.py"
    # Execute the actual limit assignments so removing the fix breaks this test.
    tree = ast.parse(source.read_text(encoding="utf8"))
    assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]).startswith("app.config['MAX_")
    ]
    def edit(name: str = '', section: int = 0, do_type: str = '') -> str:
        return request.form.get("content", "")

    def api_w_render_exter(tool: str = '') -> str:
        return request.form.get("content", "")

    hooks = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name == '_document_form_limits']
    routes = [
        node for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Call)
        and ast.unparse(node.value.func.func) == 'app.route'
        and node.value.args and isinstance(node.value.args[0], ast.Name)
        and node.value.args[0].id in ('edit', 'api_w_render_exter')
    ]
    config = ast.Module(body=assignments + hooks + routes, type_ignores=[])
    exec(compile(config, str(source), "exec"), {
        "app": app, "flask": flask, "edit": edit,
        "api_w_render_exter": api_w_render_exter,
    })
    app.add_url_rule('/login', 'login_login', edit, methods=['POST'])

    return app


class FormLimitsTest(unittest.TestCase):
    def test_long_korean_edit_round_trips(self) -> None:
        client = build_test_app().test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        for path in ('/edit/test', '/edit_from/test', '/edit_section/1/test',
                     '/api/render', '/api/render/from'):
            for count in (60_000, 100_000):
                with self.subTest(path=path, characters=count):
                    content = "가" * count
                    response = client.post(path, data={"content": content, "ver": "1"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_data(as_text=True), content)

    def test_large_multipart_text_round_trips(self) -> None:
        content = "가" * 200_000
        client = build_test_app().test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        with client.post(
            "/edit/test", data={"content": content},
            content_type="multipart/form-data",
        ) as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), content)

    def test_multipart_limits_remain_for_anonymous_and_login_forms(self) -> None:
        client = build_test_app().test_client()
        for path in ('/login', '/edit/test', '/api/render'):
            with self.subTest(path=path), client.post(
                path, data={"content": "x" * 500_001},
                content_type="multipart/form-data",
            ) as response:
                self.assertEqual(response.status_code, 413)
        with client.session_transaction() as session:
            session['id'] = 'tester'
        with client.post('/login', data={"content": "x" * 500_001},
                         content_type="multipart/form-data") as response:
            self.assertEqual(response.status_code, 413)

    def test_anonymous_forms_keep_default_limit(self) -> None:
        client = build_test_app().test_client()
        for path in ('/login', '/edit/test', '/edit_from/test', '/edit_section/1/test',
                     '/api/render', '/api/render/from'):
            with self.subTest(path=path):
                response = client.post(path, data={"content": "x" * 500_001})
                self.assertEqual(response.status_code, 413)

    def test_logged_in_login_form_keeps_default_limit(self) -> None:
        client = build_test_app().test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        response = client.post('/login', data={"content": "x" * 500_001})
        self.assertEqual(response.status_code, 413)

    def test_small_anonymous_forms_still_work(self) -> None:
        client = build_test_app().test_client()
        for path in ('/login', '/api/render'):
            with self.subTest(path=path):
                response = client.post(path, data={"content": "small"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_data(as_text=True), "small")

    def test_large_edit_does_not_change_other_request_limits(self) -> None:
        app = build_test_app()
        client = app.test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        self.assertEqual(client.post('/edit/test', data={"content": "가" * 60_000}).status_code, 200)
        self.assertEqual(app.config['MAX_FORM_MEMORY_SIZE'], 500_000)
        self.assertEqual(app.config['MAX_FORM_PARTS'], 1_000)
        with client.session_transaction() as session:
            session.clear()
        self.assertEqual(client.post('/edit/test', data={"content": "가" * 60_000}).status_code, 413)

    def test_get_request_does_not_receive_larger_limit(self) -> None:
        client = build_test_app().test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        response = client.get('/edit/test', data={"content": "x" * 500_001})
        self.assertEqual(response.status_code, 413)

    def test_total_request_limit_still_rejects_oversized_forms(self) -> None:
        app = build_test_app()
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 16_000_000)
        client = app.test_client()
        with client.session_transaction() as session:
            session['id'] = 'tester'
        response = client.post(
            "/edit/test", data={"content": "x" * 16_000_000},
        )
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
