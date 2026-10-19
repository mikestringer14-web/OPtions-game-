import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]          # repo root, so `options_screener` imports as a package
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_screener import config as config_mod  # noqa: E402
from options_screener import market_calendar  # noqa: E402

import fakes  # noqa: E402

ASOF = date(2026, 10, 16)       # a Friday session
TARGET = date(2026, 10, 19)     # the next session (Monday)
EXPIRY = date(2026, 10, 23)


@pytest.fixture
def cfg():
    # The gate scenarios use a $2.80 option (US$281/contract). capital_cad is raised here so those
    # scenarios still test gates A/B/C; the C$100 rules are tested with `cfg100` (the real config).
    return config_mod.load(overrides={"universe": {"symbols": ["ABC"]}, "account": {"capital_cad": 1000}})


@pytest.fixture
def cfg100():
    return config_mod.load(overrides={"universe": {"symbols": ["ABC"]}})


@pytest.fixture
def world():
    """A single symbol 'ABC' that passes all three gates. Tests break one piece at a time."""
    v = fakes.FakeView()
    sessions = market_calendar.sessions_between(ASOF - timedelta(days=120), ASOF)
    v.daily["ABC"] = fakes.daily(ASOF, n=60, start_px=90, end_px=100, sessions=sessions)
    # every recent morning: tight 5-min range, then a steady climb (+1.5% by 10:35)
    def climb(i):
        return 100.0 if i < 5 else 100.0 + min(i - 5, 60) * 0.025
    for d in sessions[-25:]:
        v.intraday[("ABC", d)] = fakes.minute_bars(d, climb)
    # last session closes strong in its final hour
    v.intraday[("ABC", ASOF)] = fakes.minute_bars(ASOF, lambda i: 100.0 + max(0, i - 330) * 0.02)
    v.stats["ABC"] = fakes.STATS
    ideal = fakes.snapshot("ABC", EXPIRY, 100.0)
    v.chains["ABC"] = [ideal]
    for d in sessions[-5:]:
        v.obars[(ideal.contract.occ, d)] = fakes.good_option_day(d)
    cats = fakes.FakeCatalysts({"ABC": [ASOF]})
    return v, cats, sessions
