import pytest
from snaptrade_client import ApiException

from snaptrade_watch.client import AccountRateLimiter, call_with_backoff, retry_delay


def err(status, headers=None):
    e = ApiException(status=status, reason="x")
    e.headers = headers
    return e


class Flaky:
    def __init__(self, failures, final="ok"):
        self.failures, self.final, self.calls = list(failures), final, 0

    def __call__(self, **kw):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.final


def test_account_reset_header_wins():
    d = retry_delay({"X-RateLimit-Account-Reset": "7", "Retry-After": "30"}, 0, rand=lambda a, b: 0)
    assert d == 7


def test_customer_reset_header():
    assert retry_delay({"x-ratelimit-reset": "12"}, 0, rand=lambda a, b: 0) == 12


def test_retry_after():
    assert retry_delay({"Retry-After": "3"}, 2, rand=lambda a, b: 0) == 3


def test_no_headers_exponential_with_jitter():
    assert retry_delay(None, 0, rand=lambda a, b: 0) == 1
    assert retry_delay({}, 3, rand=lambda a, b: 0) == 8
    assert retry_delay({}, 10, rand=lambda a, b: 0) == 60          # capped
    assert 2 <= retry_delay({}, 1, rand=lambda a, b: b) <= 3


def test_retries_429_then_succeeds():
    sleeps = []
    fn = Flaky([err(429, {"Retry-After": "1"}), err(429)])
    assert call_with_backoff(fn, account_id="a", sleep=sleeps.append) == "ok"
    assert fn.calls == 3 and len(sleeps) == 2


def test_gives_up_after_max_tries():
    fn = Flaky([err(429)] * 10)
    with pytest.raises(ApiException):
        call_with_backoff(fn, sleep=lambda s: None, max_tries=5)
    assert fn.calls == 5


def test_non_429_not_retried():
    fn = Flaky([err(500)])
    with pytest.raises(ApiException):
        call_with_backoff(fn, sleep=lambda s: None)
    assert fn.calls == 1


def test_per_account_min_interval():
    t = {"now": 0.0}
    slept = []
    lim = AccountRateLimiter(interval=6, clock=lambda: t["now"], sleep=slept.append)
    lim.wait("acct")
    lim.wait("acct")
    lim.wait("other")
    assert slept == [6]
