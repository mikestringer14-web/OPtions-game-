"""userSecret storage for commercial mode: a single 0600 file outside the repo."""
from __future__ import annotations

import os
import stat
from pathlib import Path


class SecretStoreError(Exception):
    pass


class SecretMissing(SecretStoreError):
    pass


def write_user_secret(path: Path, secret: str) -> None:
    """Create the file with 0600. Refuses to overwrite an existing secret."""
    if not secret:
        raise SecretStoreError("refusing to store an empty userSecret")
    path = Path(path).expanduser()
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, mode=0o700)
        os.chmod(parent, 0o700)  # mkdir's mode is filtered by umask
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SecretStoreError(f"{path} already exists; not overwriting it") from None
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, secret.encode("utf-8"))
    finally:
        os.close(fd)


def read_user_secret(path: Path) -> str:
    path = Path(path).expanduser()
    if not path.exists():
        raise SecretMissing(
            f"No userSecret at {path}. Run `python -m snaptrade_watch.cli register` once. "
            "If the user is already registered and the secret was lost, reset it with "
            "authentication.reset_snap_trade_user_secret, and store the new one carefully: "
            "losing it means deleting and recreating the SnapTrade user."
        )
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    if mode != 0o600:
        raise SecretStoreError(f"{path} has permissions {oct(mode)}; it must be exactly 0o600 (chmod 600 {path})")
    if st.st_uid != os.getuid():
        raise SecretStoreError(f"{path} is not owned by the current user; refusing to use it")
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise SecretStoreError(f"{path} is empty")
    return secret
