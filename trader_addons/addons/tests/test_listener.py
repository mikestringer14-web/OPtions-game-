"""Listener logic, plus a real websocket round-trip against a local test server."""
import asyncio
import json

import pytest
from websockets.asyncio.server import serve

import addons_common as ac
import graduation_listener as gl

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
MINT2 = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"


def snaps(prices, vols):
    """Build snapshots for minutes 1..n with cumulative volume from per-minute volume."""
    out, cum = [], 0.0
    for i, (p, v) in enumerate(zip(prices, vols), start=1):
        cum += v
        out.append({"minute": i, "price": p, "volume_cum": cum})
    return out


RANGE_PRICES = [1.00, 1.05, 0.98, 1.02, 1.04]   # 5-minute range: high 1.05, low 0.98
RANGE_VOLS = [100, 100, 100, 100, 100]


def test_breakout_fires_on_new_high_with_volume():
    s = snaps(RANGE_PRICES + [1.10], RANGE_VOLS + [250])
    sig = gl.evaluate_breakouts(s, set(), ranges=(5,))
    assert len(sig) == 1
    b = sig[0]
    assert (b["range_high"], b["range_low"], b["volume_ratio"], b["minute"]) == (1.05, 0.98, 2.5, 6)


def test_no_breakout_on_low_volume():
    s = snaps(RANGE_PRICES + [1.10], RANGE_VOLS + [80])
    assert gl.evaluate_breakouts(s, set(), ranges=(5,)) == []


def test_no_breakout_below_range_high():
    s = snaps(RANGE_PRICES + [1.05], RANGE_VOLS + [400])
    assert gl.evaluate_breakouts(s, set(), ranges=(5,)) == []


def test_no_breakout_inside_range_window():
    s = snaps(RANGE_PRICES[:4] + [2.0], RANGE_VOLS[:4] + [900])
    assert gl.evaluate_breakouts(s, set(), ranges=(5,)) == []


def test_fires_once_per_range():
    s = snaps(RANGE_PRICES + [1.10], RANGE_VOLS + [250])
    assert gl.evaluate_breakouts(s, {5}, ranges=(5,)) == []


def test_missing_data_skips_range():
    s = snaps(RANGE_PRICES + [1.10], RANGE_VOLS + [250])
    for x in s[:3]:
        x["price"] = None
    assert gl.evaluate_breakouts(s, set(), ranges=(5,)) == []


def test_parse_migration():
    ev = {"signature": "sig", "mint": MINT, "txType": "migrate", "pool": "pump-amm"}
    assert gl.parse_migration(json.dumps(ev))["mint"] == MINT
    assert gl.parse_migration('{"message":"Successfully subscribed"}') is None
    assert gl.parse_migration(json.dumps({**ev, "txType": "buy"})) is None
    assert gl.parse_migration("not json") is None


def pair(mint, price, vol_cum, liq=80000):
    return {"chainId": "solana", "dexId": "pumpswap", "pairAddress": "Pool" + mint[:10],
            "baseToken": {"address": mint}, "quoteToken": {"address": "So11111111111111111111111111111111111111112"},
            "priceUsd": str(price), "liquidity": {"usd": liq}, "volume": {"h24": vol_cum, "m5": 0},
            "txns": {"h24": {"buys": 10, "sells": 5}, "m5": {"buys": 1, "sells": 1}}}


def run_window(safety_pass):
    """Drive one mint through a full 30-minute window with a fake clock and fake APIs."""
    prices = RANGE_PRICES + [1.10] + [1.08] * 30
    vols = RANGE_VOLS + [250] + [100] * 30
    state = {"minute": 0}

    def fetch(mints):
        m = state["minute"]
        out = []
        for mint in mints:
            if m <= 30:
                out.append(pair(mint, prices[m - 1], float(sum(vols[:m]))))
            else:
                out.append(pair(mint, 1.30, 9999.0))  # follow-up prices
        return out

    calls = []

    def check(mint, pool):
        calls.append(pool)
        return {"pass": safety_pass, "reasons": [] if safety_pass else ["mint_authority_set"], "source": "fallback"}

    async def go():
        lst = gl.Listener(fetch_pairs=fetch, check_token=check)
        lst.on_message(json.dumps({"signature": "s", "mint": MINT, "txType": "migrate", "pool": "pump-amm"}))
        lst.on_message(json.dumps({"signature": "s", "mint": MINT, "txType": "migrate", "pool": "pump-amm"}))
        t = lst.trackers[MINT]
        base = t.grad_epoch
        clock = {"now": base}
        gl.time.time = lambda: clock["now"]
        try:
            for m in range(1, 31):
                state["minute"] = m
                clock["now"] = base + m * 60 + 1
                await lst.tick()
                await asyncio.sleep(0)       # let safety tasks finish
                await asyncio.gather(*lst.tasks)
            await lst.tick()
            for h in gl.FOLLOWUP_MINUTES:
                state["minute"] = 99
                clock["now"] = base + 6 * 60 + 1 + h * 60 + 1
                await lst.tick()
        finally:
            gl.time.time = __import__("time").time
        return lst, calls

    return asyncio.run(go())


def test_full_window_writes_signal_when_safe():
    lst, calls = run_window(safety_pass=True)
    grads = list(ac.read_jsonl(gl.graduations_path()))
    assert len(grads) == 1 and grads[0]["mint"] == MINT       # duplicate event ignored
    data = list(ac.read_jsonl(gl.data_path(MINT)))
    assert sum(1 for r in data if r["type"] == "snapshot") == 30
    assert sorted(r["at_minute"] for r in data if r["type"] == "safety") == [2, 10]
    assert calls[0] == "Pool" + MINT[:10]                      # pool passed to holder check
    sigs = list(ac.read_jsonl(gl.signals_path()))
    assert len(sigs) == 1
    s = sigs[0]
    assert s["watch_only"] is True and s["signal"] == "would_buy"
    assert (s["range_minutes"], s["price"], s["range_high"], s["volume_ratio"]) == (5, 1.10, 1.05, 2.5)
    outs = list(ac.read_jsonl(gl.outcomes_path()))
    assert sorted(o["horizon_min"] for o in outs) == [15, 60, 240]
    assert all(o["status"] == "ok" for o in outs)
    # +15m lands at minute 21, still inside the window; +1h/+4h use the later price
    assert {o["horizon_min"]: o["price"] for o in outs} == {15: 1.08, 60: 1.30, 240: 1.30}
    assert MINT not in lst.trackers                            # window closed


def test_unsafe_breakout_is_logged_but_no_signal():
    run_window(safety_pass=False)
    assert list(ac.read_jsonl(gl.signals_path())) == []
    b = [r for r in ac.read_jsonl(gl.data_path(MINT)) if r["type"] == "breakout"]
    assert len(b) == 1 and b[0]["safety_pass"] is False


def test_resume_after_restart(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.setattr(gl.time, "time", lambda: now)
    ac.append_jsonl(gl.graduations_path(), {"ts": "x", "epoch": now - 7 * 60, "mint": MINT, "pool": "pump-amm"})
    ac.append_jsonl(gl.graduations_path(), {"ts": "x", "epoch": now - 90 * 60, "mint": MINT2, "pool": "pump-amm"})
    for m in range(1, 7):
        ac.append_jsonl(gl.data_path(MINT), {"type": "snapshot", "minute": m, "price": 1.0, "volume_cum": m})
    ac.append_jsonl(gl.data_path(MINT), {"type": "safety", "at_minute": 2, "result": {"pass": True}})
    lst = gl.Listener(fetch_pairs=lambda m: [], check_token=lambda *a: {})
    lst.resume()
    assert list(lst.trackers) == [MINT]                        # old one not resumed
    t = lst.trackers[MINT]
    assert t.next_minute == 7 and t.safety == {2: {"pass": True}}
    assert MINT2 in lst.seen


def test_heartbeat_file():
    lst = gl.Listener(fetch_pairs=lambda m: [], check_token=lambda *a: {})
    lst.write_heartbeat()
    hb = json.loads(gl.heartbeat_path().read_text())
    assert hb["watch_only"] is True and hb["ws_connected"] is False


def test_websocket_subscribe_receive_and_reconnect(monkeypatch):
    """Real websocket client vs a local server: subscribe, get an event, survive a drop."""
    monkeypatch.setattr(gl, "MAX_BACKOFF_S", 1)
    received = []

    async def handler(ws):
        received.append(json.loads(await ws.recv()))
        n = len(received)
        await ws.send(json.dumps({"message": "Successfully subscribed to keys."}))
        mint = MINT if n == 1 else MINT2
        await ws.send(json.dumps({"signature": f"sig{n}", "mint": mint, "txType": "migrate", "pool": "pump-amm"}))
        if n == 1:
            await ws.close()              # simulate a dropped connection
        else:
            await asyncio.sleep(5)

    async def go():
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            lst = gl.Listener(ws_url=f"ws://127.0.0.1:{port}", fetch_pairs=lambda m: [],
                              check_token=lambda *a: {})
            task = asyncio.create_task(lst.ws_loop())
            for _ in range(100):
                if len(lst.seen) == 2:
                    break
                await asyncio.sleep(0.05)
            lst.stop_event.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return lst

    lst = asyncio.run(go())
    assert received == [{"method": "subscribeMigration"}] * 2
    assert lst.seen == {MINT, MINT2}
    assert lst.stats["reconnects"] >= 1
    assert [g["mint"] for g in ac.read_jsonl(gl.graduations_path())] == [MINT, MINT2]
