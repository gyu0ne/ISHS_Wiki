from contextlib import closing
import sqlite3
import unittest
from unittest.mock import AsyncMock, Mock, patch

from bs4 import BeautifulSoup
from flask import Flask

from test_render_math import get_db_table_list
from route.edit import edit_editor


def render_editor(content: str) -> str:
    app = Flask(__name__)
    with closing(sqlite3.connect(":memory:", check_same_thread=False)) as conn:
        for table, columns in get_db_table_list().items():
            column_sql = ", ".join(column + " text" for column in columns)
            conn.execute(f"create table {table} ({column_sql})")
        with app.test_request_context("/edit/test"), patch.multiple(
            "route.edit",
            get_lang=Mock(return_value="test"),
            get_main_skin_set=Mock(return_value=""),
            view_set_markup=Mock(return_value=""),
            captcha_get=AsyncMock(return_value=""),
            ip_warning=Mock(return_value=""),
            edit_button=Mock(return_value=""),
        ):
            return app.ensure_sync(edit_editor)(conn, "tester", content)


class EditorFormTest(unittest.TestCase):
    def test_original_stays_available_without_being_submitted(self) -> None:
        content = "가" * 60_000 + '<본문> & "원문"'
        editor = BeautifulSoup(render_editor(content), "html.parser")
        original = editor.select_one("#opennamu_edit_origin")
        editable = editor.select_one("#opennamu_edit_textarea")
        assert original is not None
        assert editable is not None
        self.assertEqual(original.get_text(), content)
        self.assertFalse(original.has_attr("name"))
        self.assertEqual(editable.get("name"), "content")
        self.assertEqual(editable.get_text(), content)


if __name__ == "__main__":
    unittest.main()
