"""Deterministic repository hygiene (Step 10 sections 19, 20).

Runs only when executed inside the git checkout (skips otherwise, e.g. in a packaged
build). Guards against regressions: committed runtime artifacts, conflict-copy source
files, committed secrets, and the removed legacy Node server creeping back.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "ls-files"],
            capture_output=True, text=True, timeout=20, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("not a git checkout")
    return [line for line in out.stdout.splitlines() if line]


TRACKED = _tracked_files()


def test_no_runtime_artifacts_are_tracked():
    bad = [f for f in TRACKED if f.endswith((".rdb", ".sqlite", ".sqlite3", ".coverage")) or f == "dump.rdb"]
    assert not bad, f"runtime artifacts committed: {bad}"


def test_no_conflict_copy_sources_are_tracked():
    bad = [f for f in TRACKED if re.search(r" \d+\.(py|ts|tsx|js|jsx)$", f)]
    assert not bad, f"iCloud/Finder conflict copies committed: {bad}"


def test_no_dotenv_files_are_tracked():
    bad = [f for f in TRACKED if Path(f).name == ".env" or (Path(f).name.startswith(".env.") and Path(f).name != ".env.example")]
    assert not bad, f".env files committed: {bad}"


def test_credential_bearing_dead_prefixes_are_not_tracked():
    """`legacy/legacy_node_server/`, top-level `server/` and `scratch/` all held real
    broker credentials in history and are superseded by backend/ + frontend/."""
    dead = ("legacy/legacy_node_server/", "server/", "scratch/")
    bad = [f for f in TRACKED if f.startswith(dead)]
    assert not bad, f"a credential-bearing dead prefix is tracked again: {bad[:5]}"


def test_no_conflict_copy_refs_in_git_dir():
    """iCloud/Finder has created `.git/refs/stash 2`, `.git/AUTO_MERGE 2` etc. in this
    repo before - they corrupt `git rev-list --all`. Guard against regression."""
    git_dir = _REPO_ROOT / ".git"
    if not git_dir.is_dir():
        pytest.skip("no .git dir")
    strays = [
        str(p.relative_to(git_dir))
        for p in git_dir.rglob("* [0-9]")
        if p.is_file() and re.search(r" \d+$", p.name)
    ]
    assert not strays, f"conflict-copy files inside .git: {strays}"


def test_no_obvious_hardcoded_secrets_in_shipped_code():
    """Lightweight scan of the code that actually ships. Test files legitimately contain
    fake tokens/secrets, so they are excluded."""
    patterns = [
        re.compile(r"(client_secret|api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9]{16,}['\"]", re.I),
        re.compile(r"password\s*[:=]\s*['\"][^'\"$\s]{6,}['\"]", re.I),
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # a real JWT literal
    ]
    shipped = [
        f for f in TRACKED
        if (f.startswith(("backend/app/", "frontend/src/")) and f.endswith((".py", ".ts", ".tsx")))
        and "/__tests__/" not in f and "/tests/" not in f and not Path(f).name.startswith("test_")
    ]
    hits: list[str] = []
    for rel in shipped:
        try:
            text = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pat in patterns:
            if pat.search(text):
                hits.append(rel)
                break
    assert not hits, f"possible hardcoded secret(s) in shipped code: {hits}"


# --------------------------------------------------------------------------- #
# Anti-regression: shipped runtime code (backend/app, frontend/src) must not
# reintroduce a decommissioned proprietary integration. The personal project uses
# FiinQuant + public data only.
#
# So this detector file itself never stores a proprietary host / identifier / secret
# literal, every "needle" is matched by SHA-256 digest of a lower-cased token. Only
# structural patterns (an OAuth resource-owner-password flow, a provider-client
# class shape) are plain regexes - they contain no proprietary string. Provenance
# prose ("experience at a brokerage internship") is never flagged.
# --------------------------------------------------------------------------- #
_SHIPPED_RUNTIME = ("backend/app/", "frontend/src/")

# Plain structural regexes - no proprietary literal:
_STRUCTURAL_PROHIBITED = [
    re.compile(r"grant_type['\"]?\s*[:=]\s*['\"]?password", re.I),  # broker password-grant OAuth
    re.compile(r"\b(class|def|const|function|interface)\s+\w*(iboard|kb[a-z]*client|kb[a-z]*provider)\w*", re.I),
]

# SHA-256 of lower-cased forbidden tokens (leaked credential values + decommissioned
# host / provider / env-var identifiers). The plaintext is never stored here.
_FORBIDDEN_SHA256 = {
    # leaked credential values (client_secret, 32-hex feed token, private company email)
    "9628dca305acfc22c2844a5a037f19745630b25a2be702062ada5590da81bc6c",
    "53585a231ae296b3ad6dec5be5e64bd659ca96677d45b3a62d2bb433b610dc67",
    "7a829a3610fc64361c82eba4155405270f9287b942728be6290a777361bed66d",
    # decommissioned identifiers (host / brand / env-var names), lower-cased
    "89565fd44b76f5f1f423aaee8ae0a1e9037398356df56a2f6f3eee25645930e5",
    "9a00dfa00b9f71a315b7fa31c7ded11a1f74b13f356fd814cc5c255e4940ef6c",
    "0f3635cb5c51d31cd58e7baf7f5fed657d8c40109c125d17d2397468fc1177a5",
    "39f86654ae559f95d096e143127d72f678ee2c7ae5d75539db901ddb6e4fd410",
    "2c32a2edde6525ceda39d438ab537c6a54958176fe03f7ab0a955e7027ff1b71",
    "651467fd5ced38df46447ffe647ae1e8c46a30c149b3ba9c25fc5d07f26f4750",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9@._+-]{4,120}")


def _forbidden_token_hits(text: str) -> bool:
    import hashlib

    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0).lower()
        if hashlib.sha256(tok.encode()).hexdigest() in _FORBIDDEN_SHA256:
            return True
    return False


def test_no_prohibited_proprietary_runtime_integration_in_shipped_code():
    shipped = [
        f for f in TRACKED
        if f.startswith(_SHIPPED_RUNTIME) and f.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".json"))
    ]
    hits: list[str] = []
    for rel in shipped:
        try:
            text = (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(p.search(text) for p in _STRUCTURAL_PROHIBITED) or _forbidden_token_hits(text):
            hits.append(rel)
    assert not hits, (
        "prohibited proprietary integration pattern in shipped runtime code "
        f"(FiinQuant + public data only): {hits}"
    )


def test_detector_carries_no_proprietary_plaintext():
    """This file must not itself become a place the decommissioned strings live -
    only structural regexes (no proprietary literal) and SHA-256 digests."""
    text = Path(__file__).read_text(encoding="utf-8")
    assert not _forbidden_token_hits(text)
    for pat in _STRUCTURAL_PROHIBITED:
        # structural patterns contain no host/brand token
        assert "grant_type" in pat.pattern or "iboard" in pat.pattern or "kb" in pat.pattern.lower()


def test_provenance_prose_is_still_allowed():
    """The guard is narrow: prose mentioning a brokerage as background context is fine."""
    benign = "Domain modeling reflects experience building covered-warrant tooling during an internship."
    assert not any(p.search(benign) for p in _STRUCTURAL_PROHIBITED)
    assert not _forbidden_token_hits(benign)


def test_fiinquant_is_the_only_market_data_provider_implementation():
    providers_dir = _REPO_ROOT / "backend/app/market_data/providers"
    impls = sorted(
        p.name for p in providers_dir.glob("*_provider.py")
        if p.name not in ("base_market_provider.py",)
    )
    assert impls == ["fiinquant_provider.py"], f"unexpected market-data provider implementation(s): {impls}"
