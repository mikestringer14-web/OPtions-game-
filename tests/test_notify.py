from types import SimpleNamespace
from unittest.mock import MagicMock

from conftest import ACCOUNT_ID, CONSUMER_KEY

from snaptrade_watch import notify


def test_noop_without_env(cfg_factory):
    post = MagicMock()
    assert notify.send("hello", cfg_factory(), post=post) is False
    post.assert_not_called()


def test_sends_redacted_when_configured(cfg_factory):
    token = "123456789:AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQ"
    cfg = cfg_factory(telegram_bot_token=token, telegram_chat_id="42")
    post = MagicMock(return_value=SimpleNamespace(status_code=200))
    assert notify.send(f"preview for {ACCOUNT_ID} key {CONSUMER_KEY} tok {token}", cfg, post=post) is True
    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url.endswith("/sendMessage") and post.call_args.kwargs["timeout"] == 10
    assert payload["chat_id"] == "42"
    for bad in (ACCOUNT_ID, CONSUMER_KEY, token):
        assert bad not in payload["text"]


def test_failure_does_not_leak_token(cfg_factory, caplog):
    token = "123456789:AAbbCCddEEffGGhhIIjjKKllMMnnOOppQQ"
    cfg = cfg_factory(telegram_bot_token=token, telegram_chat_id="42")

    def boom(url, **kw):
        raise ConnectionError(f"failed to reach {url}")

    assert notify.send("x", cfg, post=boom) is False
    assert token not in caplog.text
