"""No name in `app/` is used without being defined.

The same defect shipped four times: a name used in a function body with no import in scope
(`timezone` in #121, `HistoricalNoDataError` in #126, `market_session` in the nightly warm
pass from #125 onward). Importing the module succeeds, because a function body is only
resolved when it runs - and the body that failed was the one nothing exercised. The warm
pass raised NameError every five minutes in production and no test could see it.

A static check sees it without running anything. This is ruff's F821/F822/F823.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def _ruff() -> list[str] | None:
    local = Path(sys.executable).with_name("ruff")
    if local.exists():
        return [str(local)]
    found = shutil.which("ruff")
    return [found] if found else None


def test_every_name_in_app_is_defined():
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff is not installed in this environment; install it to run this guard")
    result = subprocess.run(
        [*ruff, "check", "--select", "F821,F822,F823", "--output-format", "concise", "app"],
        cwd=BACKEND, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"undefined names in app/:\n{result.stdout}{result.stderr}"
