import os
import stat

import pytest

from snaptrade_watch.secrets_store import SecretMissing, SecretStoreError, read_user_secret, write_user_secret


def test_write_creates_0600_and_0700_parent(tmp_path):
    p = tmp_path / "cfgdir" / "user_secret"
    write_user_secret(p, "s3cr3t-value")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700
    assert read_user_secret(p) == "s3cr3t-value"


def test_never_overwrites(tmp_path):
    p = tmp_path / "user_secret"
    write_user_secret(p, "first")
    with pytest.raises(SecretStoreError):
        write_user_secret(p, "second")
    assert read_user_secret(p) == "first"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o700, 0o400])
def test_wrong_permissions_refused(tmp_path, mode):
    p = tmp_path / "user_secret"
    write_user_secret(p, "value")
    os.chmod(p, mode)
    with pytest.raises(SecretStoreError, match="0o600"):
        read_user_secret(p)


def test_missing_gives_guidance(tmp_path):
    with pytest.raises(SecretMissing, match="register"):
        read_user_secret(tmp_path / "nope")


def test_secret_never_in_error_messages(tmp_path):
    p = tmp_path / "user_secret"
    write_user_secret(p, "TOPSECRET42")
    os.chmod(p, 0o644)
    with pytest.raises(SecretStoreError) as e:
        read_user_secret(p)
    assert "TOPSECRET42" not in str(e.value)


def test_empty_secret_refused(tmp_path):
    with pytest.raises(SecretStoreError):
        write_user_secret(tmp_path / "s", "")
