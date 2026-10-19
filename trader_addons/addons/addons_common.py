"""Shared helpers for the watch-only add-ons.

Everything network-related in the add-ons goes through this module, and it is
locked down on purpose:
  * HTTP GET only, and only to the hosts in ALLOWED_HTTP_HOSTS.
  * Solana JSON-RPC only for the read methods in READ_ONLY_RPC_METHODS.
    There is no way to send a transaction from here.
  * Nothing in the add-ons opens wallet files or touches keys.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

ADDONS_DIR = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("ADDONS_LOG_DIR", ADDONS_DIR / "logs"))
DATA_DIR = Path(os.environ.get("ADDONS_DATA_DIR", ADDONS_DIR / "data"))
TZ = ZoneInfo("America/Toronto")

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
ALLOWED_HTTP_HOSTS = frozenset({
    "api.rugcheck.xyz",
    "api.gopluslabs.io",
    "api.dexscreener.com",
})
READ_ONLY_RPC_METHODS = frozenset({
    "getAccountInfo",
    "getMultipleAccounts",
    "getTokenLargestAccounts",
    "getTokenSupply",
})
USER_AGENT = "trader-addons-watch-only/1.0"
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class SourceError(Exception):
    """A data source failed or returned something unusable."""


def now_local():
    return datetime.now(TZ)


def iso(dt=None):
    return (dt or now_local()).isoformat(timespec="seconds")


def iso_from_epoch(epoch):
    return datetime.fromtimestamp(epoch, TZ).isoformat(timespec="seconds")


def is_valid_mint(mint):
    return isinstance(mint, str) and bool(MINT_RE.match(mint))


_write_lock = threading.Lock()


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, separators=(",", ":"))
    with _write_lock, open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue  # a half-written line from a crash; skip it


class RateLimiter:
    """Thread-safe FIFO spacing limiter: callers queue for evenly spaced slots."""

    def __init__(self, per_minute):
        self.interval = 60.0 / float(per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        wait = slot - now
        if wait > 0:
            time.sleep(wait)


# One limiter per provider, shared by every caller in the process.
dexscreener_limiter = RateLimiter(int(os.environ.get("DEXSCREENER_RPM", "60")))
rpc_limiter = RateLimiter(int(os.environ.get("RPC_RPM", "120")))
api_limiter = RateLimiter(int(os.environ.get("SAFETY_API_RPM", "30")))  # RugCheck + GoPlus


def _secrets():
    out = []
    for name in ("HELIUS_API_KEY", "SOLANA_RPC_URL"):
        v = os.environ.get(name)
        if v:
            out.append(v)
    return out


def scrub(text):
    """Remove API keys / private RPC URLs from error text before it hits a log."""
    text = str(text)
    for s in _secrets():
        text = text.replace(s, "***")
    return re.sub(r"api-key=[^&\s'\"]+", "api-key=***", text)


def http_get_json(url, timeout=8, limiter=None):
    host = urlparse(url).hostname
    if host not in ALLOWED_HTTP_HOSTS:
        raise SourceError(f"host not allowed (watch-only): {host}")
    (limiter or api_limiter).acquire()
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    except requests.RequestException as e:
        raise SourceError(f"{type(e).__name__}: {scrub(e)}")
    if r.status_code != 200:
        raise SourceError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise SourceError("invalid JSON")


def rpc_url():
    if os.environ.get("SOLANA_RPC_URL"):
        return os.environ["SOLANA_RPC_URL"]
    key = os.environ.get("HELIUS_API_KEY")
    if key:
        return f"https://mainnet.helius-rpc.com/?api-key={key}"
    return PUBLIC_RPC


def rpc_call(method, params, timeout=8):
    if method not in READ_ONLY_RPC_METHODS:
        raise ValueError(f"RPC method not allowed (watch-only): {method}")
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    for attempt in range(2):
        rpc_limiter.acquire()
        try:
            r = requests.post(rpc_url(), json=payload, timeout=timeout,
                              headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            raise SourceError(f"{type(e).__name__}: {scrub(e)}")
        if r.status_code == 429 and attempt == 0:
            time.sleep(1.5)
            continue
        if r.status_code != 200:
            raise SourceError(f"RPC HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError:
            raise SourceError("RPC invalid JSON")
        if body.get("error"):
            err = body["error"]
            raise SourceError(f"RPC error {err.get('code')}: {scrub(err.get('message'))}")
        return body.get("result")
    raise SourceError("RPC HTTP 429")


DEXSCREENER_TOKENS_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


def dexscreener_pairs(mints, timeout=8):
    """All pairs for up to N mints, 30 per request (DexScreener's batch limit)."""
    mints = list(mints)
    pairs = []
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        body = http_get_json(DEXSCREENER_TOKENS_URL.format(",".join(chunk)),
                             timeout=timeout, limiter=dexscreener_limiter)
        if not isinstance(body, dict):
            raise SourceError("dexscreener: unexpected response")
        pairs.extend(body.get("pairs") or [])
    return pairs


def liquidity_usd(pair):
    try:
        return float((pair.get("liquidity") or {}).get("usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def best_solana_pair(pairs, mint):
    """Highest-liquidity Solana pair that trades this mint (or None)."""
    mine = [p for p in pairs
            if p.get("chainId") == "solana"
            and mint in ((p.get("baseToken") or {}).get("address"),
                         (p.get("quoteToken") or {}).get("address"))]
    if not mine:
        return None, []
    mine.sort(key=liquidity_usd, reverse=True)
    return mine[0], mine


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw):
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58[rem] + out
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * pad + out
