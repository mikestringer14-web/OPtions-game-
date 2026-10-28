"""Daily options screener. Builds one compact card per ticker and sends it to Telegram.

Data sources (set DATA_SOURCE):
  yahoo  (default) price history, option chains (bid/ask/volume/OI/IV), earnings, ex-dividend, short interest via
         the yfinance package. Free, no key, runs in GitHub Actions. Unofficial, so it can break or rate limit.
  moomoo option chains from your Moomoo account through the OpenD gateway (moomoo-api package). OpenD must be
         running and logged in on the same computer, so this mode is for running on your own machine.
Finnhub (FINNHUB_API_KEY, optional) adds the earnings calendar and the basic financials snapshot.

Greeks are always recomputed here with Black-Scholes from each contract's IV, so both sources are treated the same.
Nothing in this file places orders.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

import prob_engine as pe

log = logging.getLogger("screener")

DEFAULT_WATCHLIST = "NVDA,TSLA,AMD,META,AAPL,MSFT,AMZN,GOOGL,PLTR,AVGO"
CHAIN_COLUMNS = ["expiry", "dte", "kind", "strike", "bid", "ask", "last", "volume", "oi", "iv"]


# --------------------------------------------------------------------------- settings

def _f(name: str, default: Optional[float]) -> Optional[float]:
    v = os.environ.get(name, "").strip()
    return float(v) if v else default


# Fee presets are starting points only. Check your own fee schedule and override with COMMISSION / FX_FEE_PCT.
FEE_PRESETS = {"wealthsimple": {"commission": 0.75, "fx": 0.015}, "moomoo": {"commission": 0.65, "fx": 0.0}}


@dataclass
class Settings:
    watchlist: List[str]
    source: str = "yahoo"
    r: float = 0.04
    commission: float = 0.75
    fx_fee_pct: float = 0.015
    max_risk: Optional[float] = None
    finnhub_key: str = ""
    telegram_token: str = ""
    telegram_chat: str = ""
    iv_history_file: Path = Path("data/iv_history.csv")
    moomoo_host: str = "127.0.0.1"
    moomoo_port: int = 11111
    n_paths: int = 20000

    @classmethod
    def from_env(cls) -> "Settings":
        profile = os.environ.get("ACCOUNT_PROFILE", "wealthsimple").strip().lower()
        fees = FEE_PRESETS.get(profile, FEE_PRESETS["wealthsimple"])
        wl = os.environ.get("WATCHLIST", "").strip() or DEFAULT_WATCHLIST
        return cls(
            watchlist=[t.strip().upper() for t in wl.split(",") if t.strip()],
            source=os.environ.get("DATA_SOURCE", "yahoo").strip().lower() or "yahoo",
            r=_f("RISK_FREE_RATE", 0.04),
            commission=_f("COMMISSION", fees["commission"]),
            fx_fee_pct=_f("FX_FEE_PCT", fees["fx"]),
            max_risk=_f("MAX_RISK_PER_TRADE", None),
            finnhub_key=os.environ.get("FINNHUB_API_KEY", "").strip(),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat=os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
            iv_history_file=Path(os.environ.get("IV_HISTORY_FILE", "data/iv_history.csv")),
            moomoo_host=os.environ.get("MOOMOO_HOST", "127.0.0.1"),
            moomoo_port=int(os.environ.get("MOOMOO_PORT", "11111")),
            n_paths=int(os.environ.get("MC_PATHS", "20000")),
        )


# --------------------------------------------------------------------------- technical indicators

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def support_resistance(df: pd.DataFrame, price: float, lookback: int = 120, wing: int = 5) -> Dict[str, Optional[float]]:
    """Nearest swing low below and swing high above the price (a swing point is the extreme of +/- `wing` bars).
    Falls back to the lookback low/high if no swing point qualifies."""
    d = df.tail(lookback)
    hi, lo = d["High"].values, d["Low"].values
    highs, lows = [], []
    for i in range(wing, len(d) - wing):
        if hi[i] == hi[i - wing:i + wing + 1].max():
            highs.append(hi[i])
        if lo[i] == lo[i - wing:i + wing + 1].min():
            lows.append(lo[i])
    above = [h for h in highs if h > price]
    below = [x for x in lows if x < price]
    return {"support": max(below) if below else (float(lo.min()) if lo.min() < price else None),
            "resistance": min(above) if above else (float(hi.max()) if hi.max() > price else None)}


def technicals(df: pd.DataFrame) -> dict:
    """df: daily OHLCV with columns Open High Low Close Volume, oldest first."""
    c = df["Close"]
    price = float(c.iloc[-1])
    e9, e21, e50 = (float(ema(c, n).iloc[-1]) for n in (9, 21, 50))
    sma50 = float(c.rolling(50).mean().iloc[-1]) if len(c) >= 50 else None
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(c) >= 200 else None
    r14 = float(rsi(c).iloc[-1])
    atr_pct = float(atr(df).iloc[-1] / price * 100)
    avg_vol = df["Volume"].iloc[-21:-1].mean()
    rvol = float(df["Volume"].iloc[-1] / avg_vol) if avg_vol and avg_vol > 0 else None
    gap = float((df["Open"].iloc[-1] / c.iloc[-2] - 1) * 100) if len(c) > 1 else 0.0
    score = 0
    score += 1 if price > e21 else -1
    score += 1 if e9 > e21 else -1
    score += 1 if e21 > e50 else -1
    score += 1 if r14 > 55 else -1 if r14 < 45 else 0
    if sma200 is not None:
        score += 1 if price > sma200 else -1
    lean = "BULL" if score >= 2 else "BEAR" if score <= -2 else "NEUTRAL"
    stack = "9>21>50" if e9 > e21 > e50 else "9<21<50" if e9 < e21 < e50 else "mixed"
    out = {"price": price, "ema9": e9, "ema21": e21, "ema50": e50, "sma50": sma50, "sma200": sma200, "rsi": r14,
           "atr_pct": atr_pct, "rvol": rvol, "gap_pct": gap, "score": score, "lean": lean, "stack": stack,
           "hv20": pe.hist_vol(c.values, 20), "hv60": pe.hist_vol(c.values, 60)}
    out.update(support_resistance(df, price))
    return out


# --------------------------------------------------------------------------- option chain analytics

def is_monthly(d: date) -> bool:
    """Standard monthly expiry: the third Friday (or the Thursday before it when Friday is a holiday)."""
    if d.weekday() == 4:
        return 15 <= d.day <= 21
    return d.weekday() == 3 and 14 <= d.day <= 20 and (d + timedelta(days=1)).day <= 21


def clean_chain(chain: pd.DataFrame, spot: float, r: float) -> pd.DataFrame:
    """Drop junk quotes and add a Black-Scholes delta for every contract from its own IV."""
    ch = chain.copy()
    ch = ch[(ch["iv"] > 0.01) & (ch["iv"] < 5) & (ch["dte"] >= 0)]
    ch = ch[(ch["strike"] > spot * 0.5) & (ch["strike"] < spot * 1.5)]
    deltas = [pe.bs_greeks(spot, k, max(d, 0.5) / 365, r, iv, kind).delta
              for k, d, iv, kind in zip(ch["strike"], ch["dte"], ch["iv"], ch["kind"])]
    ch["delta"] = deltas
    ch["mid"] = np.where((ch["bid"] > 0) & (ch["ask"] >= ch["bid"]), (ch["bid"] + ch["ask"]) / 2, ch["last"])
    return ch.reset_index(drop=True)


def expiries(ch: pd.DataFrame) -> List[date]:
    return sorted(ch["expiry"].unique())


def pick_expiry(ch: pd.DataFrame, min_dte: float, target: float, monthly_only: bool = False) -> Optional[date]:
    rows = ch.drop_duplicates("expiry")[["expiry", "dte"]]
    rows = rows[rows["dte"] >= min_dte]
    if monthly_only:
        rows = rows[[is_monthly(e) for e in rows["expiry"]]]
    if rows.empty:
        return None
    return rows.iloc[(rows["dte"] - target).abs().argsort()].iloc[0]["expiry"]


def atm_iv(ch: pd.DataFrame, expiry: date, spot: float) -> Optional[float]:
    """Average call/put IV, linearly interpolated between the two strikes around spot."""
    e = ch[ch["expiry"] == expiry]
    vals = []
    for kind in ("call", "put"):
        s = e[e["kind"] == kind].sort_values("strike")
        if s.empty:
            continue
        vals.append(float(np.interp(spot, s["strike"].values, s["iv"].values)))
    return float(np.mean(vals)) if vals else None


def constant_maturity_iv(ch: pd.DataFrame, spot: float, days: float = 30) -> Optional[float]:
    """30-day ATM IV, interpolated in total variance between the expiries either side of 30 days."""
    pts = []
    for e in expiries(ch):
        d = float(ch.loc[ch["expiry"] == e, "dte"].iloc[0])
        iv = atm_iv(ch, e, spot)
        if iv and d >= 2:
            pts.append((d, iv))
    if not pts:
        return None
    below = [p for p in pts if p[0] <= days]
    above = [p for p in pts if p[0] >= days]
    if not below or not above:
        return min(pts, key=lambda p: abs(p[0] - days))[1]
    (d1, v1), (d2, v2) = below[-1], above[0]
    if d2 == d1:
        return v1
    w = (days - d1) / (d2 - d1)
    var = (1 - w) * v1 * v1 * d1 + w * v2 * v2 * d2
    return math.sqrt(var / days)


def skew_25d(ch: pd.DataFrame, expiry: date) -> Optional[float]:
    """25 delta put IV minus 25 delta call IV, in vol points. Positive = puts richer (normal for equities)."""
    e = ch[ch["expiry"] == expiry]
    out = {}
    for kind, target in (("put", -0.25), ("call", 0.25)):
        s = e[e["kind"] == kind].sort_values("delta")
        if len(s) < 2 or not (s["delta"].min() <= target <= s["delta"].max()):
            return None
        out[kind] = float(np.interp(target, s["delta"].values, s["iv"].values))
    return (out["put"] - out["call"]) * 100


def top_oi(ch: pd.DataFrame, kind: str, n: int = 3, max_dte: float = 60) -> List[tuple]:
    s = ch[(ch["kind"] == kind) & (ch["dte"] <= max_dte)].groupby("strike")["oi"].sum().sort_values(ascending=False)
    return [(float(k), int(v)) for k, v in s.head(n).items() if v > 0]


def put_call_ratios(ch: pd.DataFrame, max_dte: float = 60) -> Dict[str, Optional[float]]:
    s = ch[ch["dte"] <= max_dte]
    tot = s.groupby("kind")[["volume", "oi"]].sum()
    get = lambda kind, col: float(tot.loc[kind, col]) if kind in tot.index else 0.0  # noqa: E731
    return {"vol": get("put", "volume") / get("call", "volume") if get("call", "volume") else None,
            "oi": get("put", "oi") / get("call", "oi") if get("call", "oi") else None}


def straddle(ch: pd.DataFrame, expiry: date, spot: float) -> Optional[float]:
    e = ch[ch["expiry"] == expiry]
    if e.empty:
        return None
    k = e.iloc[(e["strike"] - spot).abs().argsort()].iloc[0]["strike"]
    c = e[(e["strike"] == k) & (e["kind"] == "call")]["mid"]
    p = e[(e["strike"] == k) & (e["kind"] == "put")]["mid"]
    if c.empty or p.empty:
        return None
    return float(c.iloc[0] + p.iloc[0])


def chain_stats(ch: pd.DataFrame, spot: float) -> dict:
    weekly = pick_expiry(ch, 1, 1)
    monthly = pick_expiry(ch, 7, 7, monthly_only=True) or pick_expiry(ch, 7, 30)
    front = monthly
    back = None
    if front is not None:
        later = ch[ch["dte"] > float(ch.loc[ch["expiry"] == front, "dte"].iloc[0]) + 14]
        back = pick_expiry(later, 0, 0, monthly_only=True) or pick_expiry(later, 0, 0)
    out = {"weekly": weekly, "monthly": monthly, "front": front, "back": back,
           "iv30": constant_maturity_iv(ch, spot), "top_oi_calls": top_oi(ch, "call"), "top_oi_puts": top_oi(ch, "put")}
    out.update({f"pcr_{k}": v for k, v in put_call_ratios(ch).items()})
    for label, e in (("weekly", weekly), ("monthly", monthly)):
        if e is None:
            continue
        dte = float(ch.loc[ch["expiry"] == e, "dte"].iloc[0])
        iv = atm_iv(ch, e, spot)
        out[f"{label}_dte"] = dte
        out[f"{label}_em"] = pe.expected_move(spot, iv, max(dte, 1)) if iv else None
        out[f"{label}_straddle"] = straddle(ch, e, spot)
    out["front_iv"] = atm_iv(ch, front, spot) if front is not None else None
    out["back_iv"] = atm_iv(ch, back, spot) if back is not None else None
    if out["front_iv"] and out["back_iv"]:
        out["term"] = "BACKWARDATION" if out["front_iv"] > out["back_iv"] * 1.02 else \
            "CONTANGO" if out["back_iv"] > out["front_iv"] * 1.02 else "FLAT"
    else:
        out["term"] = None
    out["skew25"] = skew_25d(ch, monthly) if monthly is not None else None
    atm = ch[ch["expiry"] == monthly] if monthly is not None else ch
    atm = atm.iloc[(atm["strike"] - spot).abs().argsort()].head(2)
    out["atm_liquidity"] = pe.worst_grade(pe.liquidity_grade(b, a, o, v)["grade"]
                                          for b, a, o, v in zip(atm["bid"], atm["ask"], atm["oi"], atm["volume"]))
    return out


# --------------------------------------------------------------------------- IV history (for IV rank / percentile)

def update_iv_history(path: Path, ticker: str, day: date, iv30: Optional[float]) -> List[float]:
    """Append today's 30-day ATM IV (one row per ticker per day) and return the last 252 values for the ticker.
    Free sources do not give a year of IV history, so the toolkit builds its own, one day at a time."""
    rows = []
    if path.exists():
        with path.open() as fh:
            rows = [r for r in csv.DictReader(fh)]
    rows = [r for r in rows if not (r["ticker"] == ticker and r["date"] == day.isoformat())]
    if iv30:
        rows.append({"date": day.isoformat(), "ticker": ticker, "iv30": f"{iv30:.5f}"})
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda r: (r["ticker"], r["date"]))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "ticker", "iv30"])
        w.writeheader()
        w.writerows(rows)
    hist = [float(r["iv30"]) for r in rows if r["ticker"] == ticker]
    return hist[-252:]


# --------------------------------------------------------------------------- structure selection

@dataclass
class Idea:
    name: str
    why: str
    position: Optional[pe.Position] = None
    expiry: Optional[date] = None
    legs_text: str = ""
    warnings: List[str] = field(default_factory=list)


def _nearest(e: pd.DataFrame, kind: str, delta: float) -> Optional[pd.Series]:
    s = e[(e["kind"] == kind) & (e["bid"] > 0)]
    if s.empty:
        return None
    return s.iloc[(s["delta"] - delta).abs().argsort()].iloc[0]


def _leg(row: pd.Series, qty: int) -> pe.Leg:
    return pe.Leg(row["kind"], qty, float(row["strike"]), float(row["dte"]), None, float(row["iv"]),
                  float(row["bid"]), float(row["ask"]), float(row["oi"]), float(row["volume"]))


def choose_structure(tech: dict, stats: dict, ivr: Optional[float], earnings_dte: Optional[float]) -> tuple:
    """Return (structure key, reason). Rules from the framework:
    high IV rank + range bound -> credit spreads / iron condor; low IV rank + strong trend -> debit spreads;
    front IV clearly above back IV with no event before the front expiry -> long calendar."""
    iv_hv = (stats["iv30"] / tech["hv20"]) if stats.get("iv30") and tech.get("hv20") else None
    if ivr is not None:
        rich, cheap, basis = ivr >= 50, ivr <= 30, f"IV rank {ivr:.0f}"
    elif iv_hv is not None:
        rich, cheap, basis = iv_hv >= 1.25, iv_hv <= 0.95, f"IV/HV {iv_hv:.2f} (IV rank still building)"
    else:
        rich = cheap = False
        basis = "no IV read"
    score, lean = tech["score"], tech["lean"]
    front_dte = stats.get("monthly_dte")
    event_before_front = earnings_dte is not None and front_dte is not None and earnings_dte <= front_dte
    if stats.get("front_iv") and stats.get("back_iv") and stats["front_iv"] > stats["back_iv"] * 1.05 and not event_before_front:
        f_iv, b_iv = stats["front_iv"] * 100, stats["back_iv"] * 100
        return "calendar", f"front IV {f_iv:.0f}% > back {b_iv:.0f}%, no event before front expiry"
    if rich and abs(score) <= 1:
        return "iron_condor", f"{basis}, range-bound technicals"
    if rich and lean != "NEUTRAL":
        return ("bull_put" if lean == "BULL" else "bear_call"), f"{basis}, {lean.lower()} lean: sell premium with the trend"
    if cheap and abs(score) >= 3:
        return ("bull_call" if score > 0 else "bear_put"), f"{basis}, strong trend: buy a debit spread"
    if lean != "NEUTRAL":
        return ("bull_call" if lean == "BULL" else "bear_put"), f"{basis}, {lean.lower()} lean, IV not rich: debit spread"
    return "none", f"{basis}, no trend and IV not rich: no structure has an obvious edge"


def build_idea(key: str, why: str, ch: pd.DataFrame, stats: dict, s: Settings) -> Idea:
    idea = Idea(name=key.replace("_", " "), why=why)
    if key == "none":
        return idea
    if key == "calendar":
        front, back = stats.get("front"), stats.get("back")
        if front is None or back is None:
            idea.warnings.append("no back month to pair with")
            return idea
        f = ch[(ch["expiry"] == front) & (ch["kind"] == "call") & (ch["bid"] > 0)]
        b = ch[(ch["expiry"] == back) & (ch["kind"] == "call") & (ch["bid"] > 0)]
        common = sorted(set(f["strike"]) & set(b["strike"]))
        if not common:
            idea.warnings.append("no common strike")
            return idea
        k = min(common, key=lambda x: abs(x - stats["spot"]))
        fr, br = f[f["strike"] == k].iloc[0], b[b["strike"] == k].iloc[0]
        legs = [_leg(fr, -1), _leg(br, 1)]
        idea.expiry = front
        idea.legs_text = f"-1 {front:%b%d} {k:g}C / +1 {back:%b%d} {k:g}C"
        idea.name = "long call calendar"
    else:
        exp = pick_expiry(ch, 21, 35, monthly_only=True) or pick_expiry(ch, 21, 35)
        if exp is None:
            idea.warnings.append("no 21-60 DTE expiry")
            return idea
        e = ch[ch["expiry"] == exp]
        spec = {"bull_call": [("call", 0.50, 1), ("call", 0.30, -1)],
                "bear_put": [("put", -0.50, 1), ("put", -0.30, -1)],
                "bull_put": [("put", -0.30, -1), ("put", -0.15, 1)],
                "bear_call": [("call", 0.30, -1), ("call", 0.15, 1)],
                "iron_condor": [("put", -0.10, 1), ("put", -0.20, -1), ("call", 0.20, -1), ("call", 0.10, 1)]}[key]
        rows = [(_nearest(e, kind, d), q) for kind, d, q in spec]
        if any(r is None for r, _ in rows) or len({(r["kind"], r["strike"]) for r, _ in rows}) < len(rows):
            idea.warnings.append("chain too thin to build distinct strikes")
            return idea
        legs = [_leg(r, q) for r, q in rows]
        idea.expiry = exp
        idea.legs_text = f"{exp:%b%d} " + " / ".join(
            f"{'+' if q > 0 else '-'}{r['strike']:g}{r['kind'][0].upper()}" for r, q in rows)
        idea.name = {"bull_call": "bull call debit", "bear_put": "bear put debit", "bull_put": "bull put credit",
                     "bear_call": "bear call credit", "iron_condor": "iron condor"}[key]
    idea.position = pe.Position(legs, commission_per_contract=s.commission, fx_fee_pct=s.fx_fee_pct, name=idea.name)
    return idea


# --------------------------------------------------------------------------- data sources

class YahooSource:
    """yfinance. Column names checked against yfinance 1.7.0's Ticker._options2df:
    strike, lastPrice, bid, ask, volume, openInterest, impliedVolatility (decimal). No Greeks."""

    def __init__(self):
        import yfinance as yf  # imported lazily so tests and the Moomoo path don't need it

        self.yf = yf

    def history(self, ticker: str) -> pd.DataFrame:
        df = self.yf.Ticker(ticker).history(period="2y", interval="1d", auto_adjust=False)
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    def chain(self, ticker: str, today: date, max_dte: int = 100) -> pd.DataFrame:
        t = self.yf.Ticker(ticker)
        frames = []
        for e in t.options:
            ed = datetime.strptime(e, "%Y-%m-%d").date()
            dte = (ed - today).days
            if dte < 0 or dte > max_dte:
                continue
            oc = t.option_chain(e)
            for kind, df in (("call", oc.calls), ("put", oc.puts)):
                if df is None or df.empty:
                    continue
                frames.append(pd.DataFrame({
                    "expiry": ed, "dte": float(dte), "kind": kind, "strike": df["strike"].astype(float),
                    "bid": df["bid"].fillna(0).astype(float), "ask": df["ask"].fillna(0).astype(float),
                    "last": df["lastPrice"].fillna(0).astype(float), "volume": df["volume"].fillna(0).astype(float),
                    "oi": df["openInterest"].fillna(0).astype(float), "iv": df["impliedVolatility"].astype(float)}))
            time.sleep(0.3)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CHAIN_COLUMNS)

    def spot(self, ticker: str, hist: pd.DataFrame) -> float:
        return float(hist["Close"].iloc[-1])

    def events_and_info(self, ticker: str) -> dict:
        t = self.yf.Ticker(ticker)
        out: dict = {}
        try:
            cal = t.calendar or {}
            ed = cal.get("Earnings Date") or []
            out["earnings"] = ed[0] if ed else None
            out["ex_div"] = cal.get("Ex-Dividend Date")
        except Exception as e:  # unofficial endpoint: never let it kill the run
            log.warning("%s calendar failed: %s", ticker, e)
        try:
            info = t.info or {}
        except Exception as e:
            log.warning("%s info failed: %s", ticker, e)
            info = {}
        out["short_pct_float"] = info.get("shortPercentOfFloat")
        out["days_to_cover"] = info.get("shortRatio")
        px = info.get("regularMarketPrice") or info.get("previousClose")
        # dividendRate ($/share/yr) over price is unambiguous; Yahoo has changed dividendYield's units before
        out["dividend_yield"] = info["dividendRate"] / px if info.get("dividendRate") and px else 0.0
        out["yahoo_fundamentals"] = {k: info.get(k) for k in (
            "revenueGrowth", "earningsGrowth", "returnOnEquity", "trailingPE", "forwardPE", "enterpriseToEbitda",
            "freeCashflow", "marketCap", "totalRevenue", "totalDebt", "ebitda", "trailingPegRatio")}
        return out


class MoomooSource:
    """Moomoo OpenD gateway via the moomoo-api package. Field names checked against moomoo-api 10.11.7108:
    get_option_expiration_date -> strike_time, option_expiry_date_distance
    get_option_chain(code, start, end) -> code, option_type, strike_time, strike_price (contract list, no quotes)
    get_market_snapshot(codes) -> bid_price, ask_price, last_price, volume, option_open_interest,
        option_implied_volatility, option_delta/gamma/vega/theta/rho
    IV filters in the SDK are documented in percent, so IV values above 3 are treated as percent and divided by 100.
    OpenD must be running and logged in (default 127.0.0.1:11111) with a US options quote right on your account.
    Price history still comes from Yahoo so it does not use up OpenD's historical candlestick quota."""

    SNAPSHOT_CHUNK = 200  # conservative batch size; adjust if OpenD reports a different per-call limit

    def __init__(self, host: str, port: int):
        from moomoo import RET_OK, OpenQuoteContext

        self.RET_OK = RET_OK
        self.ctx = OpenQuoteContext(host=host, port=port)
        self.yahoo = YahooSource()

    def close(self):
        self.ctx.close()

    def _ok(self, ret, data, what):
        if ret != self.RET_OK:
            raise RuntimeError(f"moomoo {what} failed: {data}")
        return data

    def history(self, ticker: str) -> pd.DataFrame:
        return self.yahoo.history(ticker)

    def chain(self, ticker: str, today: date, max_dte: int = 100) -> pd.DataFrame:
        code = f"US.{ticker}"
        exps = self._ok(*self.ctx.get_option_expiration_date(code), "expiration dates")
        frames = []
        for e in exps["strike_time"]:
            ed = datetime.strptime(str(e)[:10], "%Y-%m-%d").date()
            dte = (ed - today).days
            if dte < 0 or dte > max_dte:
                continue
            cl = self._ok(*self.ctx.get_option_chain(code, start=ed.isoformat(), end=ed.isoformat()), "option chain")
            codes = list(cl["code"])
            snaps = []
            for i in range(0, len(codes), self.SNAPSHOT_CHUNK):
                snaps.append(self._ok(*self.ctx.get_market_snapshot(codes[i:i + self.SNAPSHOT_CHUNK]), "snapshot"))
                time.sleep(0.6)
            if not snaps:
                continue
            snap = pd.concat(snaps, ignore_index=True)
            m = cl[["code", "option_type", "strike_price"]].merge(snap, on="code", how="left")
            iv = m["option_implied_volatility"].astype(float)
            if iv.median() > 3:
                iv = iv / 100.0
            frames.append(pd.DataFrame({
                "expiry": ed, "dte": float(dte), "kind": m["option_type"].astype(str).str.lower(),
                "strike": m["strike_price"].astype(float), "bid": m["bid_price"].fillna(0).astype(float),
                "ask": m["ask_price"].fillna(0).astype(float), "last": m["last_price"].fillna(0).astype(float),
                "volume": m["volume"].fillna(0).astype(float), "oi": m["option_open_interest"].fillna(0).astype(float),
                "iv": iv}))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=CHAIN_COLUMNS)

    def spot(self, ticker: str, hist: pd.DataFrame) -> float:
        snap = self._ok(*self.ctx.get_market_snapshot([f"US.{ticker}"]), "stock snapshot")
        return float(snap["last_price"].iloc[0])

    def events_and_info(self, ticker: str) -> dict:
        return self.yahoo.events_and_info(ticker)


FINNHUB = "https://finnhub.io/api/v1"
# Finnhub /stock/metric keys, tried in order. Run `python screener.py --dump-finnhub NVDA` to see what your key returns.
FINNHUB_KEYS = {
    "rev_growth": ["revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy"],
    "eps_growth": ["epsGrowthTTMYoy", "epsGrowthQuarterlyYoy"],
    "roe": ["roeTTM", "roeRfy"],
    "roic": ["roiTTM", "roiAnnual"],
    "pe": ["peTTM", "peBasicExclExtraTTM", "peNormalizedAnnual"],
    "ev_ebitda": ["evEbitdaTTM", "currentEv/ebitdaTTM"],
    "fcf_margin": ["fcfMarginTTM"],
    "net_debt_ebitda": ["netDebtToEbitdaTTM", "totalDebt/totalEquityQuarterly"],
}


def finnhub_get(path: str, key: str, get: Optional[Callable] = None, **params) -> dict:
    if get is None:
        import requests

        get = requests.get
    r = get(f"{FINNHUB}{path}", params={**params, "token": key}, timeout=15)
    if getattr(r, "status_code", 0) != 200:
        raise RuntimeError(f"finnhub {path} HTTP {getattr(r, 'status_code', '?')}")
    return r.json()


def finnhub_extras(ticker: str, key: str, today: date, get: Optional[Callable] = None) -> dict:
    out: dict = {}
    try:
        cal = finnhub_get("/calendar/earnings", key, get, symbol=ticker, **{"from": today.isoformat(),
                                                                            "to": (today + timedelta(days=120)).isoformat()})
        dates = sorted(x["date"] for x in cal.get("earningsCalendar", []) if x.get("date"))
        if dates:
            out["earnings"] = datetime.strptime(dates[0], "%Y-%m-%d").date()
    except Exception as e:
        log.warning("finnhub earnings %s: %s", ticker, type(e).__name__)
    try:
        metric = finnhub_get("/stock/metric", key, get, symbol=ticker, metric="all").get("metric", {})
        out["fundamentals"] = {name: next((metric[k] for k in keys if metric.get(k) is not None), None)
                               for name, keys in FINNHUB_KEYS.items()}
    except Exception as e:
        log.warning("finnhub metric %s: %s", ticker, type(e).__name__)
    return out


# --------------------------------------------------------------------------- per-ticker pipeline

def _days_until(d, today: date) -> Optional[float]:
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, (int, float)):  # epoch seconds
        d = datetime.utcfromtimestamp(d).date()
    return float((d - today).days)


def evaluate(ticker: str, hist: pd.DataFrame, raw_chain: pd.DataFrame, spot: float, extras: dict, s: Settings,
             today: date, iv_hist: Optional[List[float]] = None) -> dict:
    """Pure function of its inputs (no network), so it can be tested with synthetic data."""
    tech = technicals(hist)
    tech["price"] = spot
    ch = clean_chain(raw_chain, spot, s.r)
    stats = chain_stats(ch, spot)
    stats["spot"] = spot
    hist_vals = iv_hist or []
    ivr = pe.iv_rank(stats["iv30"], hist_vals) if len(hist_vals) >= 20 else None
    ivp = pe.iv_percentile(stats["iv30"], hist_vals) if len(hist_vals) >= 20 else None
    earn_dte = _days_until(extras.get("earnings"), today)
    exdiv_dte = _days_until(extras.get("ex_div"), today)
    key, why = choose_structure(tech, stats, ivr, earn_dte)
    idea = build_idea(key, why, ch, stats, s)
    res = {"ticker": ticker, "tech": tech, "stats": stats, "ivr": ivr, "ivp": ivp, "iv_hist_n": len(hist_vals),
           "earn_dte": earn_dte, "exdiv_dte": exdiv_dte, "extras": extras, "idea": idea}
    if idea.position is not None:
        pos = idea.position
        pos.dividend_yield = float(extras.get("dividend_yield") or 0.0)
        analysis = pe.analyze(pos, spot, pos.ref_iv(), tech["hv20"], s.r, n_paths=s.n_paths)
        liq = pe.worst_grade(pe.liquidity_grade(lg.bid, lg.ask, lg.oi, lg.volume)["grade"] for lg in pos.option_legs)
        window = pos.horizon
        event_in = earn_dte is not None and 0 <= earn_dte <= window
        exdiv_risk = exdiv_dte is not None and 0 <= exdiv_dte <= window and any(
            lg.qty < 0 and lg.kind == "call" for lg in pos.option_legs)
        if event_in:
            idea.warnings.append("earnings inside the trade window (IV crush risk)")
        if exdiv_risk:
            idea.warnings.append("ex-div inside window with a short call (early assignment risk)")
        res.update(analysis=analysis, liquidity=liq,
                   verdict=pe.verdict(analysis, liq, event_in, s.max_risk),
                   dominant=pe.dominant_greek(pos, spot, pos.ref_iv() or stats["iv30"] or 0.3, s.r, event_in))
    return res


# --------------------------------------------------------------------------- Telegram card

def _n(x, fmt="{:.1f}", none="n/a"):
    return none if x is None or (isinstance(x, float) and not np.isfinite(x)) else fmt.format(x)


def _fund_text(extras: dict) -> Optional[str]:
    f = extras.get("fundamentals") or {}
    y = extras.get("yahoo_fundamentals") or {}
    pick = lambda a, b, scale=1.0: f.get(a) if f.get(a) is not None else (y.get(b) * scale if y.get(b) is not None else None)  # noqa: E731
    items = [("RevG", pick("rev_growth", "revenueGrowth", 100), "{:.0f}%"),
             ("EPSG", pick("eps_growth", "earningsGrowth", 100), "{:.0f}%"),
             ("ROE", pick("roe", "returnOnEquity", 100), "{:.0f}%"),
             ("ROIC", f.get("roic"), "{:.0f}%"),
             ("PE", pick("pe", "trailingPE"), "{:.0f}"),
             ("EV/EBITDA", pick("ev_ebitda", "enterpriseToEbitda"), "{:.0f}"),
             ("FCFm", f.get("fcf_margin"), "{:.0f}%"),
             ("PEG", y.get("trailingPegRatio"), "{:.1f}")]
    parts = [f"{k} {fmt.format(v)}" for k, v, fmt in items if v is not None]
    if y.get("freeCashflow") and y.get("marketCap"):
        parts.append(f"FCFy {y['freeCashflow'] / y['marketCap'] * 100:.1f}%")
    return " ".join(parts) if parts else None


def format_card(res: dict) -> str:
    t, st, ex, idea = res["tech"], res["stats"], res["extras"], res["idea"]
    p = t["price"]
    arrow = {"BULL": "UP", "BEAR": "DOWN"}.get(t["lean"], "FLAT")
    ma = []
    if t.get("sma50"):
        ma.append(">50MA" if p > t["sma50"] else "<50MA")
    if t.get("sma200"):
        ma.append(">200MA" if p > t["sma200"] else "<200MA")
    lines = [f"{res['ticker']} ${p:,.2f} | lean {arrow} ({t['score']:+d})",
             f"{' '.join(ma)} | EMA {t['stack']} | RSI {t['rsi']:.0f} | ATR {t['atr_pct']:.1f}% | "
             f"RVol {_n(t['rvol'], '{:.1f}')} | Gap {t['gap_pct']:+.1f}%",
             f"S/R {_n(t.get('support'), '{:.2f}')} / {_n(t.get('resistance'), '{:.2f}')}"]
    iv30 = st.get("iv30")
    ivhv = iv30 / t["hv20"] if iv30 and t.get("hv20") else None
    rank = (f"IVR {res['ivr']:.0f} IVP {res['ivp']:.0f}" if res["ivr"] is not None
            else f"IVR building {res['iv_hist_n']}/20d")
    lines.append(f"IV30 {_n(iv30 and iv30 * 100, '{:.0f}')}% | {rank} | HV20 {_n(t['hv20'] and t['hv20'] * 100, '{:.0f}')} "
                 f"HV60 {_n(t['hv60'] and t['hv60'] * 100, '{:.0f}')} | IV/HV {_n(ivhv, '{:.2f}')}")
    if st.get("front") is not None:
        term = (f"Term {st['front']:%b%d} {_n(st['front_iv'] and st['front_iv'] * 100, '{:.0f}')} / "
                f"{st['back']:%b%d} {_n(st['back_iv'] and st['back_iv'] * 100, '{:.0f}')} {st['term'] or ''}"
                if st.get("back") is not None else "Term n/a")
        lines.append(f"{term} | Skew25 {_n(st.get('skew25'), '{:+.1f}')}")
    em = []
    for lbl in ("weekly", "monthly"):
        if st.get(f"{lbl}_em"):
            v = st[f"{lbl}_em"]
            sd = st.get(f"{lbl}_straddle")
            tag = "wk" if lbl == "weekly" else "mo"
            em.append(f"{tag} {st[lbl]:%b%d} +/-{v:.2f} ({v / p * 100:.1f}%)" + (f" strad {sd:.2f}" if sd else ""))
    if em:
        lines.append("EM " + " | ".join(em))
    fmt_oi = lambda xs: " ".join(f"{k:g}({v / 1000:.1f}k)" for k, v in xs) or "n/a"  # noqa: E731
    lines.append(f"OI C {fmt_oi(st['top_oi_calls'])}")
    lines.append(f"OI P {fmt_oi(st['top_oi_puts'])}")
    si = ex.get("short_pct_float")
    lines.append(f"P/C vol {_n(st.get('pcr_vol'), '{:.2f}')} OI {_n(st.get('pcr_oi'), '{:.2f}')} | "
                 f"SI {_n(si and si * 100, '{:.1f}')}% DTC {_n(ex.get('days_to_cover'), '{:.1f}')}")
    ev = []
    for lbl, d, key in (("Earn", res["earn_dte"], "earnings"), ("ExDiv", res["exdiv_dte"], "ex_div")):
        if d is not None and d >= 0:
            ev.append(f"{lbl} {ex[key]:%b%d} ({d:.0f}d){' !' if d <= 45 else ''}")
    lines.append("Events " + (" | ".join(ev) if ev else "none found"))
    fund = _fund_text(ex)
    if fund:
        lines.append("Fund " + fund)
    lines.append(f"Liq ATM {st.get('atm_liquidity', 'n/a')}")
    lines.append(f"IDEA: {idea.name} ({idea.why})")
    if idea.position is not None:
        a, v, liq, dom = res["analysis"], res["verdict"], res["liquidity"], res["dominant"]
        debit = a["entry"]
        lines.append(f"{idea.legs_text} | {'debit' if debit > 0 else 'credit'} ${abs(debit):,.0f} | legs liq {liq}")
        if liq == "F":
            lines.append("AUTO REJECT: liquidity F")
        lines.extend(pe.summary_lines(a))
        lines.append(f"Dominant: {dom['dominant']} | costs ${a['costs']['total']:.0f} + slip ${a['entry_slippage']:.0f}")
        lines.append(f">> {v['verdict']}: {'; '.join(v['reasons'])}")
    for w in idea.warnings:
        lines.append(f"! {w}")
    return "\n".join(lines)


def send_telegram(text: str, token: str, chat: str, post: Optional[Callable] = None) -> bool:
    if not token or not chat:
        return False
    if post is None:
        import requests

        post = requests.post
    try:
        r = post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=15)
        return getattr(r, "status_code", 0) == 200
    except Exception as e:  # the message can contain the URL, which contains the token
        log.warning("telegram send failed: %s", type(e).__name__)
        return False


# --------------------------------------------------------------------------- main

def run(s: Settings, today: Optional[date] = None, out=print) -> List[dict]:
    today = today or date.today()
    src = MoomooSource(s.moomoo_host, s.moomoo_port) if s.source == "moomoo" else YahooSource()
    results = []
    try:
        for tk in s.watchlist:
            try:
                hist = src.history(tk)
                if len(hist) < 60:
                    raise RuntimeError("not enough price history")
                spot = src.spot(tk, hist)
                raw = src.chain(tk, today)
                if raw.empty:
                    raise RuntimeError("empty option chain")
                extras = src.events_and_info(tk)
                if s.finnhub_key:
                    fx = finnhub_extras(tk, s.finnhub_key, today)
                    extras.update({k: v for k, v in fx.items() if v})
                iv_now = constant_maturity_iv(clean_chain(raw, spot, s.r), spot)
                iv_hist = update_iv_history(s.iv_history_file, tk, today, iv_now)
                res = evaluate(tk, hist, raw, spot, extras, s, today, iv_hist)
                card = format_card(res)
                results.append(res)
            except Exception as e:
                log.exception("%s failed", tk)
                card = f"{tk}: skipped ({type(e).__name__}: {str(e)[:120]})"
            out(card + "\n")
            send_telegram(card, s.telegram_token, s.telegram_chat)
    finally:
        if hasattr(src, "close"):
            src.close()
    footer = (f"Screener {today:%a %b %d} | source {s.source} | {len(results)}/{len(s.watchlist)} ok. "
              "POP and EV are model estimates (implied = IV, real = HV20), not promises. You decide size.")
    out(footer)
    send_telegram(footer, s.telegram_token, s.telegram_chat)
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="Options screener. Read-only: never places orders.")
    ap.add_argument("--source", choices=["yahoo", "moomoo"])
    ap.add_argument("--tickers", help="comma list, overrides WATCHLIST")
    ap.add_argument("--no-telegram", action="store_true")
    ap.add_argument("--dump-finnhub", metavar="TICKER", help="print the raw Finnhub metric keys for one ticker and exit")
    args = ap.parse_args(argv)
    s = Settings.from_env()
    if args.dump_finnhub:
        m = finnhub_get("/stock/metric", s.finnhub_key, symbol=args.dump_finnhub.upper(), metric="all").get("metric", {})
        for k in sorted(m):
            print(k, m[k])
        return 0
    if args.source:
        s.source = args.source
    if args.tickers:
        s.watchlist = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.no_telegram:
        s.telegram_token = s.telegram_chat = ""
    run(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
