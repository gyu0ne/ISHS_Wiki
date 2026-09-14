import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from route.tool.request_rate_limit import (
    check_request_rate_limit,
    reset_request_rate_limit,
    _LIMIT,
    _WINDOW_SECONDS,
)


class TestRequestRateLimit(unittest.TestCase):
    def setUp(self):
        reset_request_rate_limit()

    def test_requests_under_limit_are_allowed(self):
        for i in range(_LIMIT):
            self.assertEqual(
                check_request_rate_limit('1.2.3.4', now=1000.0 + i * 0.01),
                0,
                f'request {i + 1} should be allowed',
            )

    def test_request_over_limit_is_blocked_with_positive_retry_after(self):
        for i in range(_LIMIT):
            check_request_rate_limit('1.2.3.4', now=1000.0)

        retry_after = check_request_rate_limit('1.2.3.4', now=1000.0)
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, _WINDOW_SECONDS)

    def test_blocked_request_does_not_consume_a_slot(self):
        for i in range(_LIMIT):
            check_request_rate_limit('1.2.3.4', now=1000.0)

        # 두 번 연속 막혀도 대기 시간이 계속 늘어나지 않아야 한다.
        first_retry = check_request_rate_limit('1.2.3.4', now=1000.0)
        second_retry = check_request_rate_limit('1.2.3.4', now=1000.0)
        self.assertEqual(first_retry, second_retry)

    def test_window_expiry_allows_requests_again(self):
        for i in range(_LIMIT):
            check_request_rate_limit('1.2.3.4', now=1000.0)

        self.assertGreater(check_request_rate_limit('1.2.3.4', now=1000.0), 0)

        # 윈도우(10초)가 다 지나면 다시 허용되어야 한다.
        allowed_again = check_request_rate_limit(
            '1.2.3.4', now=1000.0 + _WINDOW_SECONDS + 0.5
        )
        self.assertEqual(allowed_again, 0)

    def test_sliding_window_frees_up_gradually(self):
        half = _LIMIT // 2
        # 절반은 t=1000.0에, 나머지 절반은 5초 뒤(t=1005.0)에 보낸다 -> 합쳐서 한도(_LIMIT) 도달.
        for _ in range(half):
            check_request_rate_limit('5.5.5.5', now=1000.0)
        for _ in range(_LIMIT - half):
            check_request_rate_limit('5.5.5.5', now=1005.0)

        # 두 그룹 다 아직 윈도우 안 -> 막힘
        self.assertGreater(check_request_rate_limit('5.5.5.5', now=1005.0), 0)

        # 첫 그룹(t=1000.0)만 윈도우 밖으로 나가는 시점 -> 두 번째 그룹만 남아 허용됨
        self.assertEqual(
            check_request_rate_limit(
                '5.5.5.5', now=1000.0 + _WINDOW_SECONDS + 0.1
            ),
            0,
        )

    def test_different_keys_are_independent(self):
        for i in range(_LIMIT):
            check_request_rate_limit('1.1.1.1', now=1000.0)

        self.assertGreater(check_request_rate_limit('1.1.1.1', now=1000.0), 0)
        # 다른 IP는 영향받지 않아야 한다.
        self.assertEqual(check_request_rate_limit('2.2.2.2', now=1000.0), 0)

    def test_concurrent_callers_are_serialized_correctly(self):
        import threading

        results = []
        results_lock = threading.Lock()

        def hammer():
            r = check_request_rate_limit('9.9.9.9', now=2000.0)
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=hammer) for _ in range(_LIMIT * 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed = sum(1 for r in results if r == 0)
        blocked = sum(1 for r in results if r > 0)
        # 동시에 몰려도 정확히 _LIMIT개만 통과해야 한다 (락으로 직렬화되므로).
        self.assertEqual(allowed, _LIMIT)
        self.assertEqual(blocked, _LIMIT)


if __name__ == '__main__':
    unittest.main()
