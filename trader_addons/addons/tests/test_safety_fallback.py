"""Safety check with mocked network. No real requests are made."""
import base64
import copy
import json

import pytest

import addons_common as ac
import safety_fallback as sf

MINT = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
POOL = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"
LP_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
WSOL = "So11111111111111111111111111111111111111112"
CREATOR = "Ey9dqpS9PBRuNDGVWFj8JJ8RJ6YybgSkfTWjvYLLUTo2"
SUPPLY = 1_000_000_000_000_000  # 1B tokens, 6 decimals


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + ac._B58.index(c)
    raw = n.to_bytes(32, "big")
    return raw


def pumpswap_pool_data(base, quote, lp):
    raw = b"\x00" * 8 + b"\x01" + b"\x00\x00" + b58decode(CREATOR) + b58decode(base) + \
        b58decode(quote) + b58decode(lp) + b"\x00" * 100
    return base64.b64encode(raw).decode()


def clean_world():
    return {
        "rugcheck": "down",
        "mint_info": {"mintAuthority": None, "freezeAuthority": None, "decimals": 6,
                      "supply": str(SUPPLY), "extensions": []},
        "goplus": {"mintable": {"status": "0"}, "freezable": {"status": "0"}, "closable": {"status": "0"},
                   "non_transferable": "0", "balance_mutable_authority": {"status": "0"},
                   "transfer_fee": {}, "transfer_fee_upgradable": {"status": "0"},
                   "transfer_hook": [], "transfer_hook_upgradable": {"status": "0"}},
        "pairs": [{"chainId": "solana", "dexId": "pumpswap", "pairAddress": POOL,
                   "baseToken": {"address": MINT}, "quoteToken": {"address": WSOL},
                   "priceUsd": "0.00012", "liquidity": {"usd": 82000}}],
        # (token account, owner, pct of supply)
        "holders": [("VaultTokenAcct1111111111111111111111111111", POOL, 62.0),
                    ("WalletTokenAcctA111111111111111111111111111", "WalletOwnerA11111111111111111111111111111", 4.0),
                    ("WalletTokenAcctB111111111111111111111111111", "WalletOwnerB11111111111111111111111111111", 3.1)],
        "lp_supply": 0,
        "fail": set(),   # source names that should error
    }


class FakeNet:
    def __init__(self, world):
        self.w = world
        self.calls = []

    def http_get_json(self, url, timeout=8, limiter=None):
        self.calls.append(url)
        if "rugcheck" in url:
            if self.w["rugcheck"] == "down":
                raise ac.SourceError("SSLError: TLS handshake failed")
            return self.w["rugcheck"]
        if "gopluslabs" in url:
            if "goplus" in self.w["fail"]:
                raise ac.SourceError("HTTP 500")
            return {"code": 1, "message": "OK", "result": {MINT: self.w["goplus"]}}
        if "dexscreener" in url:
            if "dexscreener" in self.w["fail"]:
                raise ac.SourceError("HTTP 429")
            return {"schemaVersion": "1.0.0", "pairs": self.w["pairs"]}
        raise AssertionError("unexpected url " + url)

    def rpc_call(self, method, params, timeout=8):
        self.calls.append(method)
        if "rpc" in self.w["fail"]:
            raise ac.SourceError("RPC HTTP 503")
        target = params[0]
        if method == "getAccountInfo" and target == MINT:
            return {"value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                              "data": {"parsed": {"type": "mint", "info": self.w["mint_info"]}}}}
        if method == "getAccountInfo" and target == POOL:
            return {"value": {"owner": sf.PUMPSWAP_PROGRAM,
                              "data": [pumpswap_pool_data(MINT, WSOL, LP_MINT), "base64"]}}
        if method == "getTokenSupply" and target == MINT:
            return {"value": {"amount": str(SUPPLY), "decimals": 6}}
        if method == "getTokenSupply" and target == LP_MINT:
            return {"value": {"amount": str(self.w["lp_supply"]), "decimals": 9}}
        if method == "getTokenLargestAccounts" and target == MINT:
            return {"value": [{"address": a, "amount": str(int(SUPPLY * pct / 100))}
                              for a, _, pct in self.w["holders"]]}
        if method == "getTokenLargestAccounts" and target == LP_MINT:
            return {"value": self.w.get("lp_holders", [])}
        if method == "getMultipleAccounts":
            owners = {a: o for a, o, _ in self.w["holders"]}
            owners.update(self.w.get("lp_owners", {}))
            return {"value": [{"data": {"parsed": {"info": {"owner": owners.get(a)}}}} for a in target]}
        raise AssertionError(f"unexpected rpc {method} {target}")


@pytest.fixture
def world(monkeypatch):
    w = clean_world()
    net = FakeNet(w)
    monkeypatch.setattr(ac, "http_get_json", net.http_get_json)
    monkeypatch.setattr(ac, "rpc_call", net.rpc_call)
    w["net"] = net
    return w


def test_clean_token_passes_on_fallback(world):
    res = sf.check_token(MINT)
    assert res["pass"] is True, res["reasons"]
    assert res["source"] == "fallback"
    assert res["reasons"] == []
    assert res["details"]["lp_lock"]["lp_burned"] is True
    # the 62% pool vault was recognised, not flagged as a whale
    assert res["details"]["holders"]["top_accounts"][0]["label"] == "amm_pool"
    assert "rugcheck_error" in res["details"]


def test_mint_authority_set_fails(world):
    world["mint_info"]["mintAuthority"] = CREATOR
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert "mint_authority_set" in res["reasons"]


def test_freeze_authority_set_fails(world):
    world["mint_info"]["freezeAuthority"] = CREATOR
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert "freeze_authority_set" in res["reasons"]


def test_whale_over_15_pct_fails(world):
    world["holders"].append(("WhaleTokenAcct11111111111111111111111111111",
                             "WhaleOwner111111111111111111111111111111111", 18.5))
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert any(r.startswith("whale_holder:WhaleOwner") for r in res["reasons"])


def test_burned_tokens_are_not_a_whale(world):
    world["holders"].append(("BurnTokenAcct111111111111111111111111111111",
                             "1nc1nerator11111111111111111111111111111111", 30.0))
    assert sf.check_token(MINT)["pass"] is True


def test_low_liquidity_fails(world):
    world["pairs"][0]["liquidity"]["usd"] = 12000
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert "low_liquidity" in res["reasons"]


def test_no_pair_fails(world):
    world["pairs"] = []
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert "no_solana_pair" in res["reasons"]


def test_api_error_fails(world):
    world["fail"].add("goplus")
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert "source_error:goplus" in res["reasons"]


def test_rpc_down_fails_every_rpc_source(world):
    world["fail"].add("rpc")
    res = sf.check_token(MINT)
    assert res["pass"] is False
    assert {"source_error:onchain_mint", "source_error:holders", "source_error:lp_lock"} <= set(res["reasons"])


def test_unexpected_exception_is_a_fail_not_a_crash(world, monkeypatch):
    monkeypatch.setattr(sf, "check_goplus", lambda mint: 1 / 0)
    res = sf.check_token(MINT)
    assert res["pass"] is False and "source_error:goplus" in res["reasons"]


def test_goplus_flags_fail(world):
    world["goplus"]["closable"] = {"status": "1"}
    world["goplus"]["transfer_fee"] = {"current_fee_rate": {"fee_rate": "2.5"}}
    res = sf.check_token(MINT)
    assert {"goplus_closable", "goplus_transfer_fee"} <= set(res["reasons"])


def test_token2022_transfer_fee_extension_fails(world):
    world["mint_info"]["extensions"] = [{"extension": "transferFeeConfig", "state": {
        "newerTransferFee": {"transferFeeBasisPoints": 300}, "olderTransferFee": {"transferFeeBasisPoints": 0}}}]
    assert "transfer_fee_on" in sf.check_token(MINT)["reasons"]


def test_lp_not_burned_fails(world):
    world["lp_supply"] = 1000
    world["lp_holders"] = [{"address": "LpHolderAcct1111111111111111111111111111111", "amount": "1000"}]
    world["lp_owners"] = {"LpHolderAcct1111111111111111111111111111111": CREATOR}
    res = sf.check_token(MINT)
    assert res["pass"] is False and "lp_not_burned" in res["reasons"]


def test_lp_unknown_on_other_dex_fails(world):
    world["pairs"][0]["dexId"] = "meteora"
    res = sf.check_token(MINT)
    assert res["pass"] is False and "lp_lock_unknown" in res["reasons"]


def test_rugcheck_ok_is_used_directly(world):
    world["rugcheck"] = {"score": 1, "score_normalised": 1, "risks": [], "lpLockedPct": 100}
    res = sf.check_token(MINT)
    assert res["source"] == "rugcheck" and res["pass"] is True
    assert not any("gopluslabs" in c for c in world["net"].calls)


def test_rugcheck_danger_fails(world):
    world["rugcheck"] = {"score": 9000, "risks": [{"name": "Freeze Authority still enabled", "level": "danger"}]}
    res = sf.check_token(MINT)
    assert res["source"] == "rugcheck" and res["pass"] is False
    assert res["reasons"] == ["rugcheck_danger:Freeze Authority still enabled"]


def test_rugcheck_garbage_falls_back(world):
    world["rugcheck"] = {"error": "not found"}
    res = sf.check_token(MINT)
    assert res["source"] == "fallback"


def test_invalid_mint_fails_without_network(world):
    res = sf.check_token("not-a-mint/../../x")
    assert res["pass"] is False and res["reasons"] == ["invalid_mint"]
    assert world["net"].calls == []


def test_every_check_is_logged(world):
    sf.check_token(MINT)
    world["mint_info"]["mintAuthority"] = CREATOR
    sf.check_token(MINT)
    lines = [json.loads(l) for l in sf.safety_log_path().read_text().splitlines()]
    assert [l["verdict"] for l in lines] == ["PASS", "FAIL"]
    assert all(l["mint"] == MINT and l["ts"].endswith(("-04:00", "-05:00")) for l in lines)
    assert "goplus" in lines[0]["sources_used"]


def test_cli_prints_json(world, capsys):
    code = sf.main([MINT, "--no-log"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["pass"] is True


def test_flag_parser_shapes():
    assert sf._flag_on({"status": "1"}) and not sf._flag_on({"status": "0"})
    assert sf._flag_on("1") and not sf._flag_on("0") and not sf._flag_on(None)
    assert not sf._flag_on({}) and not sf._flag_on([])
    assert sf._flag_on(["SomeHookProgram"])
    assert not sf._flag_on({"fee_rate": "0"})
    assert sf._flag_on({"weird": "shape"})  # unknown -> treated as on
