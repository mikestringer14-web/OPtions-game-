import pytest

import addons_common as ac
import daily_summary as ds
import graduation_listener as gl

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
DAY = "2026-10-20"


def test_net_return_charges_both_fills():
    assert ds.net_return(1.0, 1.0, 0.03) == pytest.approx(0.97 / 1.03 - 1)   # flat = about -5.8%
    assert ds.net_return(1.0, 1.2, 0.03) == pytest.approx(1.2 * 0.97 / 1.03 - 1)
    assert ds.net_return(1.0, None, 0.03) is None


def test_summary_counts_and_returns():
    ac.append_jsonl(gl.graduations_path(), {"ts": DAY + "T10:00:00-04:00", "epoch": 1, "mint": MINT})
    ac.append_jsonl(gl.graduations_path(), {"ts": "2026-10-19T10:00:00-04:00", "epoch": 1, "mint": "Other"})
    for m, ok in ((2, False), (10, True)):
        ac.append_jsonl(gl.data_path(MINT), {"type": "safety", "at_minute": m,
                                             "result": {"pass": ok, "source": "fallback",
                                                        "reasons": [] if ok else ["source_error:goplus"]}})
    ac.append_jsonl(gl.data_path(MINT), {"type": "breakout", "safety_pass": True, "range_minutes": 5})
    ac.append_jsonl(gl.signals_path(), {"ts": DAY + "T10:11:00-04:00", "signal_id": MINT + ":5", "mint": MINT,
                                        "price": 1.0, "range_minutes": 5})
    ac.append_jsonl(gl.outcomes_path(), {"signal_id": MINT + ":5", "horizon_min": 15, "price": 1.5, "status": "ok"})
    ac.append_jsonl(gl.outcomes_path(), {"signal_id": MINT + ":5", "horizon_min": 60, "price": None,
                                         "status": "missed"})
    s = ds.build_summary(DAY, 0.03)
    assert s["graduations"] == 1
    assert (s["safety_checks"], s["safety_passed"], s["safety_pass_rate"]) == (2, 1, 0.5)
    assert s["top_fail_reasons"] == [("source_error:goplus", 1)]
    assert s["breakouts"] == 1 and s["would_buy_signals"] == 1
    h = s["rows"][0]["horizons"]
    assert h[15]["net"] == pytest.approx(1.5 * 0.97 / 1.03 - 1)
    assert h[60]["status"] == "missed" and h[240]["status"] == "pending"
    text = ds.render(s)
    assert "+41.3%" in text and "No trades were placed" in text
