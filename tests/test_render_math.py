import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import flask
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


def import_renderer():
    original_cwd = Path.cwd()
    version_data = json.loads((ROOT / "version.json").read_text(encoding="utf8"))

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        (temp_path / "data").mkdir()
        (temp_path / "version.json").write_text(
            json.dumps(version_data), encoding="utf8"
        )
        (temp_path / "data" / "version.json").write_text(
            version_data["r_ver"], encoding="utf8"
        )

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

        try:
            os.chdir(temp_path)
            with (
                patch("subprocess.check_call") as pip_install,
                patch("subprocess.Popen") as process_restart,
                patch("os._exit") as process_exit,
            ):
                from route.tool.func import get_db_table_list, render_set

            pip_install.assert_not_called()
            process_restart.assert_not_called()
            process_exit.assert_not_called()
        finally:
            os.chdir(original_cwd)

    return get_db_table_list, render_set


get_db_table_list, render_set = import_renderer()


class MathRenderTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        curs = self.conn.cursor()
        for table, columns in get_db_table_list().items():
            column_sql = ", ".join(column + " text" for column in columns)
            curs.execute(f"create table {table} ({column_sql})")

        self.app = flask.Flask(__name__)

    def tearDown(self):
        self.conn.close()

    def render_page(self, doc_data):
        original_cwd = Path.cwd()
        try:
            os.chdir(ROOT)
            with self.app.test_request_context("/"):
                return render_set(
                    self.conn,
                    doc_name="test",
                    doc_data=doc_data,
                    data_type="view",
                    markup="namumark",
                )
        finally:
            os.chdir(original_cwd)

    def math_spans(self, page):
        return BeautifulSoup(page, "html.parser").select("span.opennamu-math")

    def script_part(self, page):
        return page[page.index("<script>") :]

    def test_math_escapes_attribute_breakout_and_script_markup(self):
        latex = (
            r'\frac{a&b}{c<d} " onmouseover="alert(1) '
            r"'single' &quot; </script><script>alert(1)</script>"
        )

        for source in (f"[math({latex})]", f"<math>{latex}</math>"):
            with self.subTest(source=source[:20]):
                page = self.render_page(source)
                spans = self.math_spans(page)

                self.assertEqual(len(spans), 1)
                self.assertEqual(spans[0]["data-tex"], latex)
                self.assertEqual(spans[0].get_text(), latex)
                self.assertNotIn("onmouseover", spans[0].attrs)
                self.assertEqual(page.count("<script>"), 1)
                self.assertEqual(page.count("</script>"), 1)
                self.assertNotIn("alert(1)", self.script_part(page))

    def test_heading_toc_uses_plain_math_text(self):
        page = self.render_page("\n= Energy [math(E=mc^2)] =\nbody\n")
        toc_end = page.index("</div><h1")
        toc_html = page[:toc_end]

        self.assertIn('href="#s-1">1. </a>Energy E=mc^2', toc_html)
        self.assertNotIn("opennamu-math", toc_html)
        self.assertEqual(self.math_spans(page)[0].get_text(), "E=mc^2")


if __name__ == "__main__":
    unittest.main()
