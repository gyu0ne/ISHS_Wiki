import os
import sqlite3
import tempfile
import threading
import unittest
from importlib.util import module_from_spec, spec_from_file_location

MODULE_PATH = os.path.join(os.path.dirname(__file__), '..', 'route', 'tool', 'ranking_views.py')
spec = spec_from_file_location('ranking_views', MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError('ranking_views module cannot be loaded')
ranking_views = module_from_spec(spec)
spec.loader.exec_module(ranking_views)
ensure_schema = ranking_views.ensure_schema
get_popular = ranking_views.get_popular
record_view = ranking_views.record_view
score_views = ranking_views.score_views


class TestRealtimePopularityStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, 'ranking.db')
        self.conn = self._connect()
        ensure_schema(self.conn, lambda sql: sql)

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        conn.execute('pragma journal_mode = wal')
        conn.execute('pragma busy_timeout = 5000')
        return conn

    def test_records_only_the_first_view_during_a_sixty_minute_window(self):
        # Given: one authenticated member and a document.
        # When: they repeat a view at 59:59 and then at 60:00.
        self.assertTrue(record_view(self.conn, 'doc-1', 'Article', 'member-1', 1000, lambda sql: sql))
        self.assertFalse(record_view(self.conn, 'doc-1', 'Article', 'member-1', 4599, lambda sql: sql))
        self.assertTrue(record_view(self.conn, 'doc-1', 'Article', 'member-1', 4600, lambda sql: sql))

        # Then: only the 60-minute boundary advances the persisted timestamp.
        row = self.conn.execute('select viewed_at from realtime_popularity_views').fetchone()
        self.assertEqual(row, (4600,))

    def test_repeated_one_thousand_times_keeps_a_single_member_document_row(self):
        # Given: one qualified member.
        # When: the page is requested 1,000 times inside an hour.
        outcomes = [
            record_view(self.conn, 'doc-1', 'Article', 'member-1', 1000 + offset, lambda sql: sql)
            for offset in range(1000)
        ]

        # Then: the first request is counted and the rest do not refresh it.
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.conn.execute('select count(*) from realtime_popularity_views').fetchone(), (1,))
        self.assertEqual(self.conn.execute('select viewed_at from realtime_popularity_views').fetchone(), (1000,))

    def test_two_sqlite_connections_count_one_simultaneous_first_view(self):
        # Given: two real SQLite connections to the same persistent database.
        second_conn = self._connect()
        try:
            barrier = threading.Barrier(2)
            outcomes = []
            errors = []
            outcomes_lock = threading.Lock()

            def view(conn):
                try:
                    barrier.wait()
                    outcome = record_view(conn, 'doc-1', 'Article', 'member-1', 1000, lambda sql: sql)
                    with outcomes_lock:
                        outcomes.append(outcome)
                except sqlite3.OperationalError as error:
                    with outcomes_lock:
                        errors.append(error)

            first_thread = threading.Thread(target=view, args=(self.conn,))
            second_thread = threading.Thread(target=view, args=(second_conn,))
            first_thread.start()
            second_thread.start()
            first_thread.join()
            second_thread.join()

            # When: both requests race to create the same member/document view.
            # Then: the atomic upsert admits exactly one first view.
            self.assertEqual(errors, [])
            self.assertEqual(sum(outcomes), 1)
            self.assertEqual(self.conn.execute('select count(*) from realtime_popularity_views').fetchone(), (1,))
        finally:
            second_conn.close()

    def test_popular_ranking_is_recent_across_midnight_and_requires_three_members(self):
        # Given: three viewers from 120 seconds before midnight and three from 8 seconds after.
        midnight = 1_735_689_600
        for member in ('a', 'b', 'c'):
            record_view(self.conn, 'yesterday', 'Yesterday', member, midnight - 120, lambda sql: sql)
            record_view(self.conn, 'recent', 'Recent', member, midnight + 8, lambda sql: sql)
        record_view(self.conn, 'too-few', 'Too few', 'a', midnight + 8, lambda sql: sql)
        record_view(self.conn, 'too-few', 'Too few', 'b', midnight + 8, lambda sql: sql)

        # When: popularity is calculated ten seconds after midnight.
        popular = get_popular(self.conn, midnight + 10, lambda sql: sql)

        # Then: recent views rank first, and fewer than three readers are excluded.
        self.assertEqual([item.title for item in popular], ['Recent', 'Yesterday'])
        self.assertEqual([item.readers for item in popular], [3, 3])
        self.assertGreater(popular[0].score, popular[1].score)

    def test_member_tokens_distinguish_school_shared_ip_and_reject_guests(self):
        # Given: three authenticated members sharing an IP (the store receives no IP key).
        for member in ('shared-ip-member-1', 'shared-ip-member-2', 'shared-ip-member-3'):
            self.assertTrue(record_view(self.conn, 'doc-1', 'Article', member, 1000, lambda sql: sql))

        # When: a guest supplies no member token.
        self.assertFalse(record_view(self.conn, 'doc-1', 'Article', '', 1000, lambda sql: sql))

        # Then: members remain distinct and no empty-token row is persisted.
        popular = get_popular(self.conn, 1000, lambda sql: sql)
        self.assertEqual([(item.title, item.readers) for item in popular], [('Article', 3)])
        self.assertEqual(self.conn.execute('select count(*) from realtime_popularity_views').fetchone(), (3,))

    def test_score_uses_the_nine_hundred_second_half_life(self):
        # Given: one current view and one view exactly one half-life old.
        # When: the pure scorer evaluates both at the current timestamp.
        score = score_views((1000, 1900), 1900)

        # Then: the older view contributes one half of the current view.
        self.assertEqual(score, 1.5)

    def test_ranking_excludes_views_older_than_sixty_minutes(self):
        # Given: three expired, exact-boundary, future, and current views.
        for member in ('a', 'b', 'c'):
            record_view(self.conn, 'expired', 'Expired', member, 1000, lambda sql: sql)
            record_view(self.conn, 'boundary', 'Boundary', member, 1001, lambda sql: sql)
            record_view(self.conn, 'future', 'Future', member, 4602, lambda sql: sql)
            record_view(self.conn, 'current', 'Current', member, 4601, lambda sql: sql)

        # When: popularity is queried at 4601, exactly 3600 seconds after Boundary.
        popular = get_popular(self.conn, 4601, lambda sql: sql)

        # Then: exact-boundary and future timestamps are outside the [0, 3600) age window.
        self.assertEqual([item.title for item in popular], ['Current'])

    def test_equal_scores_and_recency_are_ordered_by_title(self):
        # Given: two documents with identical reader counts and view timestamps.
        for member in ('a', 'b', 'c'):
            record_view(self.conn, 'z-doc', 'Z article', member, 1000, lambda sql: sql)
            record_view(self.conn, 'a-doc', 'A article', member, 1000, lambda sql: sql)

        # When: the ranking has no score or recency difference to use.
        popular = get_popular(self.conn, 1000, lambda sql: sql)

        # Then: title provides the stable final rank key.
        self.assertEqual([item.title for item in popular], ['A article', 'Z article'])


class RecordingCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 1

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))

    def fetchall(self):
        return []

    def close(self):
        pass


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()

    def cursor(self):
        return self.cursor_instance


class TestMySqlSqlContract(unittest.TestCase):
    def test_schema_and_upsert_use_mysql_safe_key_columns_and_placeholders(self):
        # Given: the existing db_change-compatible MySQL placeholder transform.
        conn = RecordingConnection()
        mysql = lambda sql: sql.replace('?', '%s')

        # When: the portable API generates its schema and write statements.
        ensure_schema(conn, mysql)
        self.assertTrue(record_view(conn, 'doc-id', 'A' * 4096, 'member', 1000, mysql))
        get_popular(conn, 1000, mysql)

        # Then: long titles are data, while fixed hashes form the unique key.
        statements = [statement for statement, _ in conn.cursor_instance.statements]
        self.assertTrue(all('?' not in statement for statement in statements))
        self.assertIn('document_key CHAR(64)', statements[0])
        self.assertIn('member_token_hash CHAR(64)', statements[0])
        self.assertIn('title TEXT', statements[0])
        self.assertIn('ON DUPLICATE KEY UPDATE', statements[-2])


if __name__ == '__main__':
    unittest.main()
