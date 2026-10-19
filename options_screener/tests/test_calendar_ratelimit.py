from datetime import date, datetime

from options_screener import market_calendar as mc
from options_screener.models import TORONTO
from options_screener.ratelimit import PacingLimiter


def at(y, m, d, h):
    return datetime(y, m, d, h, tzinfo=TORONTO)


def test_weekend_resolves_to_monday():
    assert mc.resolve_target("next", at(2026, 10, 23, 19)) == date(2026, 10, 26)    # Friday evening
    assert mc.resolve_target("next", at(2026, 10, 24, 12)) == date(2026, 10, 26)    # Saturday
    assert mc.resolve_target("next", at(2026, 10, 25, 20)) == date(2026, 10, 26)    # Sunday evening


def test_holidays_skipped():
    assert mc.resolve_target("next", at(2026, 11, 25, 20)) == date(2026, 11, 27)    # Thanksgiving skipped
    assert mc.resolve_target("next", at(2026, 12, 24, 20)) == date(2026, 12, 28)    # Christmas + weekend
    assert mc.resolve_target("2026-07-03") == date(2026, 7, 6)                      # observed July 4th


def test_early_morning_on_a_session_is_today():
    assert mc.resolve_target("next", at(2026, 10, 20, 6)) == date(2026, 10, 20)


def test_previous_session():
    assert mc.previous_session(date(2026, 10, 26)) == date(2026, 10, 23)
    assert mc.previous_session(date(2026, 11, 27)) == date(2026, 11, 25)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_identical_request_waits_15s():
    c = Clock()
    lim = PacingLimiter(clock=c, sleep=c.sleep)
    lim.acquire("k", "req")
    assert lim.acquire("k", "req") >= 15


def test_same_contract_burst_limited():
    c = Clock()
    lim = PacingLimiter(clock=c, sleep=c.sleep)
    for i in range(5):
        assert lim.acquire("k", f"r{i}") == 0
    assert lim.acquire("k", "r5") > 0                      # 6th within 2 s must wait


def test_sixty_per_ten_minutes_and_bid_ask_counts_double():
    c = Clock()
    lim = PacingLimiter(clock=c, sleep=c.sleep, same_contract_max=1000)
    for i in range(30):
        lim.acquire(f"c{i}", f"r{i}", "BID_ASK")           # 30 x 2 = 60 units
    assert lim.acquire("x", "y") > 500                     # next one waits for the window
