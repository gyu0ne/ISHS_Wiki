import json
import os
import sqlite3
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import flask


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


class MathSpanParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.spans = []
        self.current_span = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "span" and "opennamu-math" in classes:
            self.current_span = {"attributes": attributes, "text": ""}
            self.spans.append(self.current_span)

    def handle_data(self, data):
        if self.current_span is not None:
            self.current_span["text"] += data

    def handle_endtag(self, tag):
        if tag == "span" and self.current_span is not None:
            self.current_span = None


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

    def render_page(self, doc_data, data_type="view"):
        original_cwd = Path.cwd()
        try:
            os.chdir(ROOT)
            with self.app.test_request_context("/"):
                return render_set(
                    self.conn,
                    doc_name="test",
                    doc_data=doc_data,
                    data_type=data_type,
                    markup="namumark",
                )
        finally:
            os.chdir(original_cwd)

    def math_spans(self, page):
        parser = MathSpanParser()
        parser.feed(page)
        return parser.spans

    def script_part(self, page):
        return page[page.index("<script>") :]

    def test_macro_and_tag_math_have_data_and_visible_fallback(self):
        for source, latex in (
            (r"[math(x^2 + \alpha)]", r"x^2 + \alpha"),
            (r"<math>E=mc^2 & c<d</math>", "E=mc^2 & c<d"),
        ):
            with self.subTest(source=source):
                page = self.render_page(source)
                spans = self.math_spans(page)

                self.assertEqual(len(spans), 1)
                self.assertEqual(spans[0]["attributes"]["data-tex"], latex)
                self.assertEqual(spans[0]["text"], latex)
                self.assertNotIn(latex, self.script_part(page))

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
                self.assertEqual(spans[0]["attributes"]["data-tex"], latex)
                self.assertEqual(spans[0]["text"], latex)
                self.assertNotIn("onmouseover", spans[0]["attributes"])
                self.assertEqual(page.count("<script>"), 1)
                self.assertEqual(page.count("</script>"), 1)
                self.assertNotIn("alert(1)", self.script_part(page))

    def test_multiple_formulas_keep_order_and_unique_ids(self):
        page = self.render_page(r"[math(a)] then <math>b&c</math> then [math(\gamma)]")
        spans = self.math_spans(page)

        self.assertEqual(
            [span["attributes"]["data-tex"] for span in spans],
            ["a", "b&c", r"\gamma"],
        )
        self.assertEqual([span["text"] for span in spans], ["a", "b&c", r"\gamma"])
        self.assertEqual(len({span["attributes"]["id"] for span in spans}), 3)

    def test_api_render_modes_return_math_html_without_latex_in_javascript(self):
        latex = r"\sqrt{x&y}"
        for data_type in ("api_view", "api_include"):
            with self.subTest(data_type=data_type):
                html_data, js_data = self.render_page(
                    f"[math({latex})]", data_type=data_type
                )
                span = self.math_spans(html_data)[0]

                self.assertEqual(span["attributes"]["data-tex"], latex)
                self.assertEqual(span["text"], latex)
                self.assertNotIn(latex, js_data)

    def test_included_page_renders_nested_math(self):
        self.conn.execute(
            "insert into data (title, data, type) values (?, ?, ?)",
            ("Child", "before <math>c+d</math> after", ""),
        )

        page = self.render_page("[include(Child)]")
        spans = self.math_spans(page)

        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["attributes"]["data-tex"], "c+d")
        self.assertEqual(spans[0]["text"], "c+d")
        self.assertNotIn("c+d", self.script_part(page))

    def test_heading_toc_uses_plain_math_text(self):
        page = self.render_page("\n= Energy [math(E=mc^2)] =\nbody\n")
        toc_end = page.index("</div><h1")
        toc_html = page[:toc_end]

        self.assertIn('href="#s-1">1. </a>Energy E=mc^2', toc_html)
        self.assertNotIn("opennamu-math", toc_html)
        self.assertEqual(self.math_spans(page)[0]["text"], "E=mc^2")


if __name__ == "__main__":
    unittest.main()
