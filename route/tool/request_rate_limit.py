import math
import threading
import time

# 새로고침/봇 트래픽 폭주로부터 서버를 보호하기 위한 요청 단위 rate limit.
# 이 앱은 단일 hypercorn 프로세스로 돌기 때문에(워커/DB 없이) 메모리 내 상태로 충분하다.

_WINDOW_SECONDS = 10
_LIMIT = 40
_MAX_TRACKED_KEYS = 5000

_lock = threading.Lock()
_buckets = {}


def check_request_rate_limit(key, now=None):
    """key(보통 클라이언트 IP)가 지금 요청해도 되는지 확인한다.

    허용되면 0을, 제한에 걸리면 다시 시도해야 하는 초(1 이상)를 반환한다.
    """
    current_time = time.time() if now is None else float(now)
    cutoff = current_time - _WINDOW_SECONDS

    with _lock:
        attempts = [t for t in _buckets.get(key, ()) if t > cutoff]

        if len(attempts) >= _LIMIT:
            _buckets[key] = attempts
            return max(1, int(math.ceil(attempts[0] + _WINDOW_SECONDS - current_time)))

        attempts.append(current_time)
        _buckets[key] = attempts

        if len(_buckets) > _MAX_TRACKED_KEYS:
            _cleanup(cutoff)

        return 0


def _cleanup(cutoff):
    stale_keys = [
        bucket_key for bucket_key, attempts in _buckets.items()
        if not attempts or attempts[-1] <= cutoff
    ]
    for bucket_key in stale_keys:
        del _buckets[bucket_key]


def reset_request_rate_limit():
    """테스트 전용: 누적된 상태를 초기화한다."""
    with _lock:
        _buckets.clear()
