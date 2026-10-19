"""RESEARCH ONLY: no order code anywhere, no broker module on the screen path, no secrets in the repo."""
import re
import subprocess
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ORDER_CALLS = re.compile(r"\.placeOrder\(|\.cancelOrder\(|\.reqGlobalCancel\(|\bLimitOrder\(|\bMarketOrder\(|"
                         r"\bStopOrder\(|\bStopLimitOrder\(|\bwhatIfOrder|\bOrder\(|\bplace_order\(|\bsubmit_order\(")
SECRET_PATTERNS = [
    re.compile(r"\b(?:DU|DF|U)\d{6,9}\b"),                                   # IBKR account numbers
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}['\"]"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)apikey=[A-Za-z0-9]{12,}"),
]


def source_files():
    return [p for p in PKG.rglob("*.py") if ".venv" not in p.parts and "tests" not in p.parts]


def repo_files():
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "."], cwd=PKG,
                             capture_output=True, text=True, check=True).stdout.split()
        return [PKG / f for f in out]
    except Exception:
        return [p for p in PKG.rglob("*") if p.is_file() and ".venv" not in p.parts and "cache" not in p.parts]


def test_no_order_calls_anywhere():
    offenders = []
    for p in source_files():
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if ORDER_CALLS.search(line) and not line.strip().startswith("#"):
                offenders.append(f"{p.relative_to(PKG)}:{i}: {line.strip()}")
    assert offenders == [], offenders
    assert not (PKG / "paper.py").exists()


def test_optional_ibkr_provider_stays_read_only_and_unused():
    src = (PKG / "providers" / "ibkr.py").read_text()
    assert "readonly=True" in src and "PAPER_PORTS" in src
    for p in source_files():
        if p.name != "ibkr.py":
            assert "providers.ibkr" not in p.read_text() and "from .ibkr" not in p.read_text(), p


def test_no_secrets_in_repo_files():
    hits = []
    for p in repo_files():
        if p.suffix in {".png", ".jpg", ".pdf"} or not p.exists() or p.name == "test_security.py":
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            continue
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{p.relative_to(PKG)}: {m.group(0)[:12]}...")
    assert hits == [], hits


def test_env_files_ignored_and_example_is_empty():
    ignore = (PKG / ".gitignore").read_text()
    assert ".env" in ignore and "logs/" in ignore
    for line in (PKG / ".env.example").read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        if any(s in key for s in ("KEY", "ACCOUNT", "SECRET", "TOKEN", "PASSWORD")):
            assert val.strip() == "", f"{key} must be empty in .env.example"
    assert not any(p.name == ".env" for p in repo_files())
