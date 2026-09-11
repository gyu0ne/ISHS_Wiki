import concurrent.futures
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / 'route'
    / 'tool'
    / 'password_rate_limit.py'
)
SPEC = importlib.util.spec_from_file_location('password_rate_limit', MODULE_PATH)
password_rate_limit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(password_rate_limit)

consume_password_attempt = password_rate_limit.consume_password_attempt
initialize_password_rate_limit = password_rate_limit.initialize_password_rate_limit


class PasswordRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / 'rate-limit.db')
        self.conn = self._connect()
        initialize_password_rate_limit(self.conn, 'sqlite')

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _connect(self):
        return sqlite3.connect(
            self.db_path,
            isolation_level=None,
            timeout=10,
        )

    def _consume(self, account='account-1', client_ip='192.0.2.1', scope='password', now=1000):
        return consume_password_attempt(
            self.conn,
            'sqlite',
            account,
            client_ip,
            scope=scope,
            now=now,
        )

    def test_fifth_attempt_is_allowed_and_sixth_is_blocked(self):
        self.assertEqual([self._consume() for _ in range(5)], [0] * 5)
        self.assertEqual(self._consume(), 60)

        rows = self.conn.execute(
            'SELECT attempts_json FROM password_rate_limit'
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(len(json.loads(row[0])) == 5 for row in rows))

    def test_retry_uses_ceiling(self):
        for _ in range(5):
            self._consume(now=1000)

        self.assertEqual(self._consume(now=1000.1), 60)
        self.assertEqual(self._consume(now=1001.1), 59)

    def test_rolling_window_expires_at_the_exact_boundary(self):
        for timestamp in range(5):
            self.assertEqual(self._consume(now=timestamp), 0)

        self.assertEqual(self._consume(now=10), 50)
        self.assertEqual(self._consume(now=60), 0)
        self.assertEqual(self._consume(now=60.1), 1)
        self.assertEqual(self._consume(now=61), 0)

    def test_out_of_order_timestamp_keeps_the_newer_expiry(self):
        self.assertEqual(self._consume(now=1004), 0)
        self.assertEqual(self._consume(now=1000), 0)

        rows = self.conn.execute(
            'SELECT attempts_json, expires_at FROM password_rate_limit'
        ).fetchall()
        self.assertTrue(all(json.loads(row[0]) == [1000.0, 1004.0] for row in rows))
        self.assertTrue(all(row[1] == 1064 for row in rows))

    def test_account_and_ip_limits_are_independent(self):
        for index in range(5):
            self.assertEqual(
                self._consume(account='shared-account', client_ip='ip-' + str(index)),
                0,
            )
        self.assertEqual(
            self._consume(account='shared-account', client_ip='unused-ip'),
            60,
        )
        self.assertEqual(self._consume(account='other-account', client_ip='other-ip'), 0)

        for index in range(5):
            self.assertEqual(
                self._consume(account='ip-account-' + str(index), client_ip='shared-ip'),
                0,
            )
        self.assertEqual(
            self._consume(account='sixth-ip-account', client_ip='shared-ip'),
            60,
        )

    def test_rejected_attempt_consumes_neither_bucket(self):
        for index in range(5):
            self.assertEqual(
                self._consume(account='blocked-account', client_ip='old-ip-' + str(index)),
                0,
            )
        self.assertEqual(
            self._consume(account='blocked-account', client_ip='fresh-ip'),
            60,
        )

        results = [
            self._consume(account='fresh-account-' + str(index), client_ip='fresh-ip')
            for index in range(5)
        ]
        self.assertEqual(results, [0] * 5)
        self.assertEqual(
            self._consume(account='fresh-account-6', client_ip='fresh-ip'),
            60,
        )

    def test_scopes_have_separate_account_and_ip_buckets(self):
        for _ in range(5):
            self.assertEqual(self._consume(scope='password'), 0)

        self.assertEqual(self._consume(scope='password'), 60)
        self.assertEqual(self._consume(scope='second-factor'), 0)
        self.assertEqual(self._consume(scope='riro'), 0)

    def test_state_persists_across_connections(self):
        for _ in range(5):
            self.assertEqual(self._consume(), 0)
        self.conn.close()

        self.conn = self._connect()
        self.assertEqual(self._consume(), 60)

    def test_simultaneous_connections_allow_only_five_attempts(self):
        worker_count = 8
        barrier = threading.Barrier(worker_count)

        def consume_once():
            conn = self._connect()
            try:
                barrier.wait(timeout=5)
                return consume_password_attempt(
                    conn,
                    'sqlite',
                    'concurrent-account',
                    'concurrent-ip',
                    now=1000,
                )
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(lambda _: consume_once(), range(worker_count)))

        self.assertEqual(results.count(0), 5)
        self.assertEqual(results.count(60), 3)

    def test_expired_rows_are_cleaned_and_identifiers_are_hashed(self):
        account = 'person@example.test'
        client_ip = '203.0.113.123'
        self.assertEqual(self._consume(account=account, client_ip=client_ip, now=1), 0)

        stored_keys = [
            row[0]
            for row in self.conn.execute(
                'SELECT bucket_key FROM password_rate_limit'
            ).fetchall()
        ]
        self.assertEqual(len(stored_keys), 2)
        self.assertTrue(all(len(key) == 64 for key in stored_keys))
        self.assertNotIn(account, json.dumps(stored_keys))
        self.assertNotIn(client_ip, json.dumps(stored_keys))

        self.assertEqual(
            self._consume(account='new-account', client_ip='new-ip', now=61),
            0,
        )
        remaining = self.conn.execute(
            'SELECT COUNT(*) FROM password_rate_limit'
        ).fetchone()[0]
        self.assertEqual(remaining, 2)

    def test_database_errors_are_propagated(self):
        self.conn.close()
        with self.assertRaises(sqlite3.ProgrammingError):
            self._consume()
        self.conn = self._connect()


if __name__ == '__main__':
    unittest.main()
