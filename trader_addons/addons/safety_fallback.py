#!/usr/bin/env python3
"""Backup safety check for when RugCheck is down. WATCH-ONLY: reads data, never trades.

    python safety_fallback.py <mint> [--pool <pool_address>]

check_token(mint) -> {pass, reasons, source, details, ...}
  1. RugCheck summary (8s timeout). If it answers with a usable report, that is the verdict.
  2. Otherwise the fallback runs every check below and FAILS on any red flag or any
     source error. Missing data never passes.
"""
import argparse
import base64
import json
import os
import sys
import time

import addons_common as ac

RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"
GOPLUS_URL = "https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={}"

MAX_HOLDER_PCT = float(os.environ.get("SAFETY_MAX_HOLDER_PCT", "15"))
MIN_LIQUIDITY_USD = float(os.environ.get("SAFETY_MIN_LIQUIDITY_USD", "50000"))
LP_BURNED_MIN_PCT = float(os.environ.get("SAFETY_LP_BURNED_MIN_PCT", "95"))
# Optional: also fail RugCheck reports above this normalised score (0-100). Unset = off.
RUGCHECK_MAX_SCORE = os.environ.get("RUGCHECK_MAX_SCORE")

BURN_ADDRESSES = {
    "1nc1nerator11111111111111111111111111111111": "incinerator",
    "11111111111111111111111111111111": "system_program",
}
# Owners of AMM pool vaults. Tokens held here are pool liquidity, not a whale.
AMM_VAULT_OWNERS = {
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": "raydium_amm_v4_authority",
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL": "raydium_cpmm_authority",
}
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

GOPLUS_FLAGS = {
    "mintable": "goplus_mintable",
    "freezable": "goplus_freezable",
    "closable": "goplus_closable",
    "non_transferable": "goplus_non_transferable",
    "balance_mutable_authority": "goplus_balance_mutable",
    "transfer_fee": "goplus_transfer_fee",
    "transfer_fee_upgradable": "goplus_transfer_fee_upgradable",
    "transfer_hook": "goplus_transfer_hook",
    "transfer_hook_upgradable": "goplus_transfer_hook_upgradable",
}


def safety_log_path():
    return ac.LOG_DIR / "safety_checks.jsonl"


# ---------------------------------------------------------------- RugCheck

def rugcheck_verdict(summary):
    """Map a RugCheck summary to (pass, reasons). Raises SourceError if unusable."""
    if not isinstance(summary, dict) or ("risks" not in summary and "score" not in summary):
        raise ac.SourceError("rugcheck: unexpected response shape")
    reasons = []
    for risk in summary.get("risks") or []:
        if str(risk.get("level", "")).lower() == "danger":
            reasons.append("rugcheck_danger:" + str(risk.get("name", "unknown")))
    if RUGCHECK_MAX_SCORE is not None:
        score = summary.get("score_normalised")
        if score is None or float(score) > float(RUGCHECK_MAX_SCORE):
            reasons.append(f"rugcheck_score:{score}")
    return not reasons, reasons


# ---------------------------------------------------------------- fallback checks
# Each returns (reasons, details). Raising SourceError marks the source as failed.

def check_mint_onchain(mint):
    res = ac.rpc_call("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}])
    value = (res or {}).get("value")
    if not value:
        raise ac.SourceError("mint account not found")
    data = value.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    if not parsed or parsed.get("type") != "mint":
        raise ac.SourceError("account is not a parsed token mint")
    info = parsed.get("info") or {}
    reasons = []
    if info.get("mintAuthority") is not None:
        reasons.append("mint_authority_set")
    if info.get("freezeAuthority") is not None:
        reasons.append("freeze_authority_set")

    ext_names = []
    for ext in info.get("extensions") or []:
        name = ext.get("extension")
        state = ext.get("state") or {}
        ext_names.append(name)
        if name == "transferFeeConfig":
            bps = [(state.get(k) or {}).get("transferFeeBasisPoints", 0)
                   for k in ("newerTransferFee", "olderTransferFee")]
            if any(int(b or 0) > 0 for b in bps):
                reasons.append("transfer_fee_on")
        elif name == "transferHook" and state.get("programId"):
            reasons.append("transfer_hook_on")
        elif name == "permanentDelegate" and state.get("delegate"):
            reasons.append("permanent_delegate_set")
        elif name == "nonTransferable":
            reasons.append("non_transferable")
        elif name == "defaultAccountState" and state.get("accountState") == "frozen":
            reasons.append("default_account_frozen")

    details = {
        "mintAuthority": info.get("mintAuthority"),
        "freezeAuthority": info.get("freezeAuthority"),
        "decimals": info.get("decimals"),
        "supply": info.get("supply"),
        "program": value.get("owner"),
        "extensions": ext_names,
    }
    return reasons, details


def _flag_on(v):
    """GoPlus mixes "1"/"0" strings, {status: ...} objects, lists and fee objects."""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() == "1"
    if isinstance(v, list):
        return any(_flag_on(x) if isinstance(x, dict) and "status" in x else True for x in v)
    if isinstance(v, dict):
        if "status" in v:
            return _flag_on(v["status"])
        if not v:
            return False
        nums = list(_numbers(v))
        return any(n > 0 for n in nums) if nums else True  # unknown shape: treat as on
    return True


def _numbers(obj):
    if isinstance(obj, dict):
        for x in obj.values():
            yield from _numbers(x)
    elif isinstance(obj, list):
        for x in obj:
            yield from _numbers(x)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, str):
        try:
            yield float(obj)
        except ValueError:
            return


def check_goplus(mint):
    body = ac.http_get_json(GOPLUS_URL.format(mint), timeout=8)
    if not isinstance(body, dict) or body.get("code") != 1:
        raise ac.SourceError(f"goplus code {body.get('code') if isinstance(body, dict) else '?'}")
    result = body.get("result") or {}
    data = result.get(mint) or next((v for k, v in result.items() if k.lower() == mint.lower()), None)
    if not data:
        raise ac.SourceError("goplus: token not indexed yet")
    reasons = [reason for key, reason in GOPLUS_FLAGS.items() if _flag_on(data.get(key))]
    details = {key: data.get(key) for key in GOPLUS_FLAGS}
    return reasons, details


def check_liquidity(mint):
    pairs = ac.dexscreener_pairs([mint])
    top, sol_pairs = ac.best_solana_pair(pairs, mint)
    if not top:
        return ["no_solana_pair", "low_liquidity"], {"pairs": 0, "pair_addresses": []}
    liq = ac.liquidity_usd(top)
    reasons = [] if liq >= MIN_LIQUIDITY_USD else ["low_liquidity"]
    details = {
        "pairs": len(sol_pairs),
        "pair_addresses": [p.get("pairAddress") for p in sol_pairs if p.get("pairAddress")],
        "top_pair": top.get("pairAddress"),
        "dex": top.get("dexId"),
        "liquidity_usd": liq,
        "price_usd": top.get("priceUsd"),
        "min_liquidity_usd": MIN_LIQUIDITY_USD,
    }
    return reasons, details


def _owners_of(token_accounts):
    res = ac.rpc_call("getMultipleAccounts", [token_accounts, {"encoding": "jsonParsed"}])
    owners = {}
    for addr, acct in zip(token_accounts, (res or {}).get("value") or []):
        try:
            owners[addr] = acct["data"]["parsed"]["info"]["owner"]
        except (TypeError, KeyError):
            owners[addr] = None  # unknown owner counts as a wallet (conservative)
    return owners


def check_holders(mint, pool_addresses=()):
    supply_res = ac.rpc_call("getTokenSupply", [mint])
    supply = int(((supply_res or {}).get("value") or {}).get("amount") or 0)
    if supply <= 0:
        raise ac.SourceError("token supply is zero or missing")
    largest = ((ac.rpc_call("getTokenLargestAccounts", [mint]) or {}).get("value")) or []
    if not largest:
        raise ac.SourceError("no holder data")
    owners = _owners_of([a["address"] for a in largest])
    pools = set(pool_addresses)

    reasons, top = [], []
    for acct in largest:
        addr = acct["address"]
        owner = owners.get(addr)
        pct = int(acct.get("amount") or 0) * 100.0 / supply
        if addr in pools or owner in pools:
            label = "amm_pool"
        elif owner in AMM_VAULT_OWNERS:
            label = AMM_VAULT_OWNERS[owner]
        elif owner in BURN_ADDRESSES or addr in BURN_ADDRESSES:
            label = "burn"
        else:
            label = "wallet"
        top.append({"account": addr, "owner": owner, "pct": round(pct, 3), "label": label})
        if label == "wallet" and pct > MAX_HOLDER_PCT:
            reasons.append(f"whale_holder:{owner or addr}:{pct:.1f}%")
    wallets = [t["pct"] for t in top if t["label"] == "wallet"]
    details = {"max_wallet_pct": max(wallets) if wallets else 0.0,
               "limit_pct": MAX_HOLDER_PCT, "top_accounts": top[:10]}
    return reasons, details


def _pumpswap_lp_mint(pool_address, mint):
    """Read the PumpSwap pool account and pull out its LP mint.

    Layout (Anchor): 8 discriminator, u8 bump, u16 index, creator, base_mint,
    quote_mint, lp_mint, ... The base/quote mint check guards against a layout change.
    """
    res = ac.rpc_call("getAccountInfo", [pool_address, {"encoding": "base64"}])
    value = (res or {}).get("value")
    if not value or value.get("owner") != PUMPSWAP_PROGRAM:
        return None
    raw = base64.b64decode(value["data"][0])
    if len(raw) < 139:
        return None
    keys = [ac.b58encode(raw[o:o + 32]) for o in (43, 75, 107)]
    base_mint, quote_mint, lp_mint = keys
    if mint not in (base_mint, quote_mint):
        return None
    return lp_mint


def check_lp_lock(mint, liquidity_details):
    details = {"lp_burned": None, "method": None}
    pool = (liquidity_details or {}).get("top_pair")
    dex = (liquidity_details or {}).get("dex")
    if not pool or dex != "pumpswap":
        details["note"] = f"no free LP-lock data for dex={dex}"
        return ["lp_lock_unknown"], details
    lp_mint = _pumpswap_lp_mint(pool, mint)
    if not lp_mint:
        details["note"] = "could not decode PumpSwap pool"
        return ["lp_lock_unknown"], details
    details.update(method="pumpswap_lp_mint", lp_mint=lp_mint)
    lp_supply = int(((ac.rpc_call("getTokenSupply", [lp_mint]) or {}).get("value") or {}).get("amount") or 0)
    if lp_supply == 0:
        details.update(lp_burned=True, burned_pct=100.0)
        return [], details
    largest = ((ac.rpc_call("getTokenLargestAccounts", [lp_mint]) or {}).get("value")) or []
    owners = _owners_of([a["address"] for a in largest]) if largest else {}
    burned = sum(int(a.get("amount") or 0) for a in largest
                 if owners.get(a["address"]) in BURN_ADDRESSES or a["address"] in BURN_ADDRESSES)
    burned_pct = burned * 100.0 / lp_supply
    details.update(burned_pct=round(burned_pct, 2), lp_burned=burned_pct >= LP_BURNED_MIN_PCT)
    return ([] if details["lp_burned"] else ["lp_not_burned"]), details


# ---------------------------------------------------------------- main entry

def _run(name, fn, reasons, details, sources):
    sources.append(name)
    try:
        r, d = fn()
        reasons.extend(r)
        details[name] = d
        return d
    except Exception as e:  # any failure, even a bug, is a FAIL, never a pass
        reasons.append(f"source_error:{name}")
        details[name] = {"error": ac.scrub(f"{type(e).__name__}: {e}")}
        return None


def check_token(mint, pool_address=None, log=True):
    started = time.monotonic()
    result = {"mint": mint, "pass": False, "reasons": [], "source": "fallback",
              "sources_used": [], "details": {}, "checked_at": ac.iso()}

    if not ac.is_valid_mint(mint):
        result["reasons"] = ["invalid_mint"]
        return _finish(result, started, log)

    try:
        summary = ac.http_get_json(RUGCHECK_URL.format(mint), timeout=8)
        ok, reasons = rugcheck_verdict(summary)
        result.update({"pass": ok, "reasons": reasons, "source": "rugcheck", "sources_used": ["rugcheck"]})
        result["details"]["rugcheck"] = {k: summary.get(k) for k in
                                         ("score", "score_normalised", "lpLockedPct", "tokenProgram", "risks")}
        return _finish(result, started, log)
    except Exception as e:
        result["details"]["rugcheck_error"] = ac.scrub(f"{type(e).__name__}: {e}")

    reasons, details, sources = [], result["details"], ["rugcheck(failed)"]
    _run("onchain_mint", lambda: check_mint_onchain(mint), reasons, details, sources)
    _run("goplus", lambda: check_goplus(mint), reasons, details, sources)
    liq = _run("dexscreener", lambda: check_liquidity(mint), reasons, details, sources)
    pools = set((liq or {}).get("pair_addresses") or [])
    if pool_address:
        pools.add(pool_address)
    _run("holders", lambda: check_holders(mint, pools), reasons, details, sources)
    if liq is None:
        reasons.append("lp_lock_unknown")  # can't find the pool without DexScreener
    else:
        _run("lp_lock", lambda: check_lp_lock(mint, liq), reasons, details, sources)

    result.update({"pass": not reasons, "reasons": reasons, "sources_used": sources})
    return _finish(result, started, log)


def _finish(result, started, log):
    result["elapsed_s"] = round(time.monotonic() - started, 2)
    if log:
        ac.append_jsonl(safety_log_path(), {
            "ts": result["checked_at"],
            "mint": result["mint"],
            "verdict": "PASS" if result["pass"] else "FAIL",
            "reasons": result["reasons"],
            "source": result["source"],
            "sources_used": result["sources_used"],
            "details": result["details"],
        })
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Watch-only token safety check (RugCheck with fallback).")
    p.add_argument("mint")
    p.add_argument("--pool", help="known AMM pool address to exclude from holder concentration")
    p.add_argument("--no-log", action="store_true")
    args = p.parse_args(argv)
    res = check_token(args.mint, pool_address=args.pool, log=not args.no_log)
    print(json.dumps(res, indent=2, default=str))
    return 0 if res["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
