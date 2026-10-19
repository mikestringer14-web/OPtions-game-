"""Guards that the add-ons cannot trade or touch keys."""
import re
from pathlib import Path

import pytest

import addons_common as ac

ADDONS = Path(__file__).resolve().parents[1]
FORBIDDEN = [r"wallet\.json", r"jup\.ag", r"jupiter", r"/swap", r"sendTransaction", r"sendRawTransaction",
             r"Keypair", r"private_?key", r"secret_?key", r"\bimport buy\b", r"\bimport sell\b",
             r"positions\.json", r"trading_meta", r"sleeve_exit"]


def source_files():
    return [p for p in ADDONS.glob("*.py")] + [ADDONS / "run_listener.sh", ADDONS / "graduation-listener.service"]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_trading_or_key_code(pattern):
    hits = [f"{p.name}:{i}" for p in source_files()
            for i, line in enumerate(p.read_text().splitlines(), 1)
            if re.search(pattern, line, re.I) and not line.lstrip().startswith("#")]
    assert hits == [], f"{pattern} found in {hits}"


def test_rpc_refuses_write_methods():
    for m in ("sendTransaction", "requestAirdrop", "simulateTransaction"):
        with pytest.raises(ValueError):
            ac.rpc_call(m, [])


def test_http_refuses_other_hosts():
    for url in ("https://quote-api.jup.ag/v6/swap", "https://lite-api.jup.ag/swap/v1/quote", "http://localhost/x"):
        with pytest.raises(ac.SourceError):
            ac.http_get_json(url)


def test_api_key_is_scrubbed(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "abc123secret")
    assert "abc123secret" not in ac.scrub("failed https://mainnet.helius-rpc.com/?api-key=abc123secret")
