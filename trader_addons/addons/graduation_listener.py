#!/usr/bin/env python3
"""Pump.fun graduation listener. WATCH-ONLY: it logs, it never trades.

  * Subscribes to PumpPortal migrations over websocket (auto-reconnect 1s..60s, ping 30s).
  * Logs every graduation to logs/graduations.jsonl.
  * Takes 1-minute DexScreener snapshots for 30 minutes per mint -> data/<mint>.jsonl.
  * Runs safety_fallback.check_token at ~2 and ~10 minutes.
  * Logs a "would_buy" line to logs/watch_signals.jsonl when safety passes AND a
    5/10/15-minute opening-range breakout fires on above-average volume.
  * Re-prices each would-buy at +15m/+1h/+4h -> logs/signal_outcomes.jsonl.
  * Writes logs/listener_heartbeat.txt every minute.
"""
import asyncio
import json
import logging
import logging.handlers
import os
import signal
import sys
import time

from websockets.asyncio.client import connect

import addons_common as ac
import safety_fallback

WS_URL = os.environ.get("PUMPPORTAL_WS", "wss://pumpportal.fun/api/data")
SNAPSHOT_MINUTES = int(os.environ.get("SNAPSHOT_MINUTES", "30"))
SAFETY_AT_MINUTES = (2, 10)
RANGE_MINUTES = (5, 10, 15)
VOLUME_RATIO_MIN = float(os.environ.get("BREAKOUT_VOLUME_RATIO", "1.0"))
FOLLOWUP_MINUTES = (15, 60, 240)
FOLLOWUP_MAX_LATE_S = 600
TICK_S = 5
HEARTBEAT_S = 60
PING_S = 30
MAX_BACKOFF_S = 60

log = logging.getLogger("listener")


def graduations_path():
    return ac.LOG_DIR / "graduations.jsonl"


def signals_path():
    return ac.LOG_DIR / "watch_signals.jsonl"


def outcomes_path():
    return ac.LOG_DIR / "signal_outcomes.jsonl"


def heartbeat_path():
    return ac.LOG_DIR / "listener_heartbeat.txt"


def data_path(mint):
    return ac.DATA_DIR / f"{mint}.jsonl"


# ---------------------------------------------------------------- pure logic

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def snapshot_from_pair(pair):
    """Flatten a DexScreener pair. h24 volume/txns are cumulative because the pair is new."""
    if not pair:
        return {"pair_found": False, "price": None}
    vol = pair.get("volume") or {}
    tx = pair.get("txns") or {}
    return {
        "pair_found": True,
        "pair_address": pair.get("pairAddress"),
        "dex": pair.get("dexId"),
        "price": _f(pair.get("priceUsd")),
        "price_native": _f(pair.get("priceNative")),
        "liquidity_usd": ac.liquidity_usd(pair),
        "market_cap": _f(pair.get("marketCap") or pair.get("fdv")),
        "volume_m5": _f(vol.get("m5")),
        "volume_h1": _f(vol.get("h1")),
        "volume_cum": _f(vol.get("h24")),
        "buys_m5": (tx.get("m5") or {}).get("buys"),
        "sells_m5": (tx.get("m5") or {}).get("sells"),
        "buys_cum": (tx.get("h24") or {}).get("buys"),
        "sells_cum": (tx.get("h24") or {}).get("sells"),
    }


def minute_volumes(snapshots):
    """Per-minute volume = change in cumulative volume between consecutive snapshots."""
    out, prev = {}, None
    for s in sorted(snapshots, key=lambda s: s["minute"]):
        cum = s.get("volume_cum")
        if cum is None:
            continue
        out[s["minute"]] = max(0.0, cum - (prev if prev is not None else 0.0))
        prev = cum
    return out


def evaluate_breakouts(snapshots, already_fired, ranges=RANGE_MINUTES, ratio_min=VOLUME_RATIO_MIN):
    """Check the newest snapshot for opening-range breakouts not already fired.

    Range = min/max of 1-minute closes in minutes 1..N (closes only: DexScreener has
    no intraminute high/low). Breakout = newest close > range high AND that minute's
    volume > ratio_min x the range's average minute volume.
    """
    priced = [s for s in snapshots if s.get("price") is not None]
    if not priced:
        return []
    latest = max(priced, key=lambda s: s["minute"])
    vols = minute_volumes(snapshots)
    out = []
    for n in ranges:
        if n in already_fired or latest["minute"] <= n:
            continue
        window = [s for s in priced if 1 <= s["minute"] <= n]
        if len(window) < max(3, int(n * 0.6)):
            continue  # too many missing minutes to trust the range
        high = max(s["price"] for s in window)
        low = min(s["price"] for s in window)
        wvols = [vols[s["minute"]] for s in window if s["minute"] in vols]
        avg = sum(wvols) / len(wvols) if wvols else 0.0
        cur = vols.get(latest["minute"])
        if avg <= 0 or cur is None:
            continue
        ratio = cur / avg
        if latest["price"] > high and ratio > ratio_min:
            out.append({
                "range_minutes": n, "minute": latest["minute"], "price": latest["price"],
                "range_high": high, "range_low": low, "volume_ratio": round(ratio, 3),
                "minute_volume": cur, "avg_range_volume": round(avg, 2),
                "liquidity_usd": latest.get("liquidity_usd"), "pair_address": latest.get("pair_address"),
            })
    return out


def latest_safety(safety):
    """Most recent completed safety result (10-minute beats 2-minute)."""
    for m in sorted(safety, reverse=True):
        if safety[m] is not None:
            return m, safety[m]
    return None, None


def parse_migration(message):
    """Return the event dict if this websocket message is a migration, else None."""
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not ac.is_valid_mint(data.get("mint")):
        return None
    tx_type = str(data.get("txType", "")).lower()
    if tx_type and tx_type not in ("migrate", "migration"):
        return None
    return data


# ---------------------------------------------------------------- state

class Tracker:
    def __init__(self, mint, grad_epoch, pool=None, signature=None):
        self.mint = mint
        self.grad_epoch = grad_epoch
        self.pool = pool
        self.signature = signature
        self.snapshots = []
        self.next_minute = 1
        self.safety = {}          # minute -> result (None while running)
        self.fired = set()
        self.pair_address = None

    def due(self, now):
        return self.next_minute <= SNAPSHOT_MINUTES and now >= self.grad_epoch + self.next_minute * 60

    def finished(self):
        return self.next_minute > SNAPSHOT_MINUTES and all(v is not None for v in self.safety.values()) \
            and len(self.safety) == len(SAFETY_AT_MINUTES)


class Listener:
    def __init__(self, ws_url=WS_URL, fetch_pairs=None, check_token=None):
        self.ws_url = ws_url
        self.fetch_pairs = fetch_pairs or ac.dexscreener_pairs
        self.check_token = check_token or safety_fallback.check_token
        self.trackers = {}
        self.seen = set()
        self.followups = []        # dicts: signal_id, mint, horizon, due_epoch, entry_price
        self.connected = False
        self.last_message_epoch = None
        self.started_epoch = time.time()
        self.stats = {"graduations": 0, "snapshots": 0, "safety_checks": 0, "signals": 0, "reconnects": 0}
        self.stop_event = asyncio.Event()
        self.safety_sem = asyncio.Semaphore(4)
        self.tasks = set()

    # ---- startup resume (so a crash/restart doesn't lose open windows)
    def resume(self):
        now = time.time()
        for g in ac.read_jsonl(graduations_path()):
            mint, epoch = g.get("mint"), g.get("epoch")
            if not mint or not epoch:
                continue
            self.seen.add(mint)
            if now - epoch > (SNAPSHOT_MINUTES + 1) * 60 or mint in self.trackers:
                continue
            t = Tracker(mint, epoch, g.get("pool"), g.get("signature"))
            for rec in ac.read_jsonl(data_path(mint)):
                if rec.get("type") == "snapshot":
                    t.snapshots.append(rec)
                    t.next_minute = max(t.next_minute, rec["minute"] + 1)
                elif rec.get("type") == "safety":
                    t.safety[rec["at_minute"]] = rec["result"]
                elif rec.get("type") == "breakout":
                    t.fired.add(rec["range_minutes"])
            self.trackers[mint] = t
        done = {(o["signal_id"], o["horizon_min"]) for o in ac.read_jsonl(outcomes_path())}
        for s in ac.read_jsonl(signals_path()):
            for h in FOLLOWUP_MINUTES:
                if (s["signal_id"], h) not in done:
                    self.followups.append({"signal_id": s["signal_id"], "mint": s["mint"], "horizon_min": h,
                                           "due_epoch": s["epoch"] + h * 60, "entry_price": s["price"]})
        if self.trackers or self.followups:
            log.info("resumed %d open windows, %d pending follow-ups", len(self.trackers), len(self.followups))

    # ---- websocket
    async def ws_loop(self):
        backoff = 1
        while not self.stop_event.is_set():
            try:
                async with connect(self.ws_url, ping_interval=PING_S, ping_timeout=20,
                                   open_timeout=15, close_timeout=5, max_size=2 ** 20) as ws:
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    self.connected = True
                    log.info("connected to %s, subscribed to migrations", self.ws_url)
                    async for message in ws:
                        backoff = 1
                        self.last_message_epoch = time.time()
                        self.on_message(message)
                        if self.stop_event.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("websocket error: %s", ac.scrub(f"{type(e).__name__}: {e}"))
            finally:
                if self.connected:
                    self.stats["reconnects"] += 1
                self.connected = False
            if self.stop_event.is_set():
                break
            log.info("reconnecting in %ss", backoff)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    def on_message(self, message):
        event = parse_migration(message)
        if event is None:
            log.info("ws message (not a migration): %s", str(message)[:300])
            return
        mint = event["mint"]
        if mint in self.seen:
            return
        self.seen.add(mint)
        epoch = time.time()
        pool = event.get("pool")
        rec = {"ts": ac.iso_from_epoch(epoch), "epoch": round(epoch, 3), "mint": mint, "pool": pool,
               "signature": event.get("signature"), "raw": event}
        ac.append_jsonl(graduations_path(), rec)
        ac.append_jsonl(data_path(mint), {"type": "graduation", **rec})
        self.trackers[mint] = Tracker(mint, epoch, pool, event.get("signature"))
        self.stats["graduations"] += 1
        log.info("GRADUATION %s pool=%s", mint, pool)

    # ---- per-tick work
    async def tick(self):
        now = time.time()
        due = [t for t in self.trackers.values() if t.due(now)]
        fups = [f for f in self.followups if now >= f["due_epoch"]]
        mints = sorted({t.mint for t in due} | {f["mint"] for f in fups})
        pairs = []
        if mints:
            try:
                pairs = await asyncio.to_thread(self.fetch_pairs, mints)
            except Exception as e:
                log.warning("dexscreener fetch failed for %d mints: %s", len(mints), ac.scrub(e))
                pairs = None
        for t in due:
            self.record_snapshot(t, pairs, now)
        for f in fups:
            self.record_followup(f, pairs, now)
        for t in list(self.trackers.values()):
            self.maybe_start_safety(t, now)
            if t.finished():
                del self.trackers[t.mint]
                log.info("window closed for %s", t.mint)

    def record_snapshot(self, t, pairs, now):
        minute = max(t.next_minute, min(SNAPSHOT_MINUTES, int((now - t.grad_epoch) // 60)))
        t.next_minute = minute + 1
        if pairs is None:
            snap = {"pair_found": False, "price": None, "error": "fetch_failed"}
        else:
            pair, _ = ac.best_solana_pair(pairs, t.mint)
            snap = snapshot_from_pair(pair)
        rec = {"type": "snapshot", "ts": ac.iso_from_epoch(now), "epoch": round(now, 3),
               "minute": minute, **snap}
        t.snapshots.append(rec)
        if snap.get("pair_address"):
            t.pair_address = snap["pair_address"]
        ac.append_jsonl(data_path(t.mint), rec)
        self.stats["snapshots"] += 1
        for b in evaluate_breakouts(t.snapshots, t.fired):
            self.on_breakout(t, b, now)

    def on_breakout(self, t, b, now):
        t.fired.add(b["range_minutes"])
        at, res = latest_safety(t.safety)
        safe = bool(res and res.get("pass"))
        ac.append_jsonl(data_path(t.mint), {"type": "breakout", "ts": ac.iso_from_epoch(now),
                                            "safety_pass": safe, "safety_at_minute": at, **b})
        if not safe:
            log.info("breakout %s %sm range, blocked by safety (%s)", t.mint, b["range_minutes"],
                     (res or {}).get("reasons", "no result yet"))
            return
        sig = {"ts": ac.iso_from_epoch(now), "epoch": round(now, 3), "signal": "would_buy",
               "watch_only": True, "signal_id": f"{t.mint}:{b['range_minutes']}", "mint": t.mint,
               "graduated_at": ac.iso_from_epoch(t.grad_epoch), "safety_source": res.get("source"),
               "safety_at_minute": at, **b}
        ac.append_jsonl(signals_path(), sig)
        self.stats["signals"] += 1
        for h in FOLLOWUP_MINUTES:
            self.followups.append({"signal_id": sig["signal_id"], "mint": t.mint, "horizon_min": h,
                                   "due_epoch": now + h * 60, "entry_price": b["price"]})
        log.info("WOULD-BUY (log only) %s price=%s range=%sm ratio=%s", t.mint, b["price"],
                 b["range_minutes"], b["volume_ratio"])

    def record_followup(self, f, pairs, now):
        self.followups.remove(f)
        late = now - f["due_epoch"]
        rec = {"ts": ac.iso_from_epoch(now), "signal_id": f["signal_id"], "mint": f["mint"],
               "horizon_min": f["horizon_min"], "entry_price": f["entry_price"], "late_s": round(late)}
        if late > FOLLOWUP_MAX_LATE_S:
            rec.update(status="missed", price=None)
        elif pairs is None:
            rec.update(status="fetch_failed", price=None)
        else:
            pair, _ = ac.best_solana_pair(pairs, f["mint"])
            price = _f(pair.get("priceUsd")) if pair else None
            rec.update(status="ok" if price is not None else "no_pair", price=price,
                       liquidity_usd=ac.liquidity_usd(pair) if pair else None)
        ac.append_jsonl(outcomes_path(), rec)

    def maybe_start_safety(self, t, now):
        for m in SAFETY_AT_MINUTES:
            if m not in t.safety and now >= t.grad_epoch + m * 60:
                t.safety[m] = None  # running
                task = asyncio.create_task(self.run_safety(t, m))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

    async def run_safety(self, t, m):
        async with self.safety_sem:
            try:
                res = await asyncio.to_thread(self.check_token, t.mint, t.pair_address)
            except Exception as e:
                res = {"pass": False, "reasons": ["source_error:check_token"], "source": "fallback",
                       "details": {"error": ac.scrub(e)}}
        t.safety[m] = res
        self.stats["safety_checks"] += 1
        ac.append_jsonl(data_path(t.mint), {"type": "safety", "ts": ac.iso(), "at_minute": m, "result": res})
        log.info("safety %s @%sm: %s %s", t.mint, m, "PASS" if res.get("pass") else "FAIL",
                 res.get("reasons"))

    # ---- loops
    async def tick_loop(self):
        while not self.stop_event.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("tick failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=TICK_S)
            except asyncio.TimeoutError:
                pass

    def write_heartbeat(self):
        hb = {"ts": ac.iso(), "pid": os.getpid(), "ws_connected": self.connected,
              "last_ws_message": ac.iso_from_epoch(self.last_message_epoch) if self.last_message_epoch else None,
              "uptime_s": round(time.time() - self.started_epoch), "tracking_now": len(self.trackers),
              "pending_followups": len(self.followups), "watch_only": True, **self.stats}
        path = heartbeat_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(hb, indent=2) + "\n")
        os.replace(tmp, path)

    async def heartbeat_loop(self):
        while not self.stop_event.is_set():
            try:
                self.write_heartbeat()
            except Exception:
                log.exception("heartbeat failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=HEARTBEAT_S)
            except asyncio.TimeoutError:
                pass

    async def run(self):
        self.resume()
        loops = [asyncio.create_task(c) for c in (self.ws_loop(), self.tick_loop(), self.heartbeat_loop())]
        await self.stop_event.wait()
        for task in loops + list(self.tasks):
            task.cancel()
        await asyncio.gather(*loops, *self.tasks, return_exceptions=True)
        self.write_heartbeat()
        log.info("listener stopped")


def setup_logging():
    ac.LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(ac.LOG_DIR / "listener.log", maxBytes=10_000_000, backupCount=5)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fmt.converter = lambda *a: ac.now_local().timetuple()
    handler.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    if sys.stderr.isatty():  # under the supervisor, listener.log is enough
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        log.addHandler(console)


async def amain():
    setup_logging()
    listener = Listener()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, listener.stop_event.set)
    log.info("graduation listener starting (WATCH-ONLY, no trading code loaded), pid=%s", os.getpid())
    await listener.run()


if __name__ == "__main__":
    asyncio.run(amain())
