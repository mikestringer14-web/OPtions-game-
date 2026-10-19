import pytest

from snaptrade_watch.config import ConfigError, load_config, mask_id, parse_live_trading, redact

BASE = {"SNAPTRADE_CLIENT_ID": "cid", "SNAPTRADE_CONSUMER_KEY": "ck"}


@pytest.mark.parametrize("value", [None, "", "True", "TRUE", "1", "yes", "on", " true", "true ", "false"])
def test_live_trading_is_false_unless_exactly_true(value):
    assert parse_live_trading(value) is False


def test_live_trading_exact_true():
    assert parse_live_trading("true") is True
    assert load_config({**BASE, "LIVE_TRADING": "true"}).live_trading is True
    assert load_config({**BASE, "LIVE_TRADING": "True"}).live_trading is False
    assert load_config(BASE).live_trading is False


def test_defaults_personal_mode():
    cfg = load_config(BASE)
    assert cfg.auth_mode == "personal" and cfg.user_id is None and cfg.max_order_value_cad == 500
    assert "ck" not in repr(cfg)                     # consumer key hidden from repr


def test_missing_keys():
    with pytest.raises(ConfigError):
        load_config({"SNAPTRADE_CLIENT_ID": "x"})


def test_commercial_needs_stable_non_email_user_id():
    with pytest.raises(ConfigError):
        load_config({**BASE, "SNAPTRADE_AUTH_MODE": "commercial"})
    with pytest.raises(ConfigError):
        load_config({**BASE, "SNAPTRADE_AUTH_MODE": "commercial", "SNAPTRADE_USER_ID": "mike@example.com"})
    cfg = load_config({**BASE, "SNAPTRADE_AUTH_MODE": "commercial", "SNAPTRADE_USER_ID": "mike-local-1"})
    assert cfg.user_id == "mike-local-1"


def test_bad_cap():
    with pytest.raises(ConfigError):
        load_config({**BASE, "MAX_ORDER_VALUE_CAD": "lots"})


def test_mask_and_redact():
    assert mask_id("11111111-2222-3333-4444-555566667777") == "****7777"
    assert mask_id("ab") == "****"
    text = "acct 11111111-2222-3333-4444-555566667777 number 51234567 key SECRETKEY price 31.50"
    out = redact(text, ["SECRETKEY"])
    assert "SECRETKEY" not in out and "555566667777" not in out and "51234567" not in out
    assert "****7777" in out and "****4567" in out and "31.50" in out
