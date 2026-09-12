import json
import os
import sqlite3
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if os.getcwd() != ROOT:
    os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# route/tool/func.py reads data/version.json at import and tries pip installs when it is missing
_cache_path = os.path.join(ROOT, "data", "version.json")
if not os.path.exists(_cache_path):
    with open(os.path.join(ROOT, "version.json"), encoding = "utf8") as file_data:
        release_ver = json.load(file_data)["r_ver"]

    os.makedirs(os.path.dirname(_cache_path), exist_ok = True)
    with open(_cache_path, "w", encoding = "utf8") as file_data:
        file_data.write(release_ver)

import flask

from route.tool.func import get_db_table_list, render_set


class MathRenderTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        curs = self.conn.cursor()
        for table, cols in get_db_table_list().items():
            curs.execute("create table %s (%s)" % (table, ", ".join(col + " text" for col in cols)))

        self.app = flask.Flask(__name__)

    def render_page(self, doc_data):
        with self.app.test_request_context("/"):
            return render_set(self.conn, doc_name = "test", doc_data = doc_data, data_type = "view", markup = "namumark")

    def script_part(self, page):
        return page[page.index("<script>"):]

    def test_math_latex_stays_out_of_script(self):
        page = self.render_page("[math(x^2)]")

        self.assertIn('<span class="opennamu-math"', page)
        self.assertIn('data-tex="x^2"', page)
        self.assertNotIn("x^2", self.script_part(page))

    def test_math_tag_latex_stays_out_of_script(self):
        page = self.render_page("<math>E=mc^2</math>")

        self.assertIn('data-tex="E=mc^2"', page)
        self.assertNotIn("E=mc^2", self.script_part(page))

    def test_script_close_in_latex_is_escaped(self):
        page = self.render_page("[math(</script><script>alert(1)</script>)]")

        self.assertIn('data-tex="&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;"', page)
        self.assertEqual(page.count("<script>"), 1)
        self.assertEqual(page.count("</script>"), 1)
        self.assertNotIn("alert", self.script_part(page))


if __name__ == "__main__":
    unittest.main()
