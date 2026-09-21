"""Every CLI command a workflow runs must actually parse.

`fundamentals-refresh.yml` shipped with `--json` AFTER the subcommand. It is a GLOBAL
flag, so argparse exited 2 with "unrecognized arguments: --json" and the scheduled run
died on its first real invocation - after checkout, after a 41s pip install, and only
reachable by running the workflow. Nothing in the test suite looked at what the workflow
actually types.

This reads the invocations straight out of the YAML and parses them with the real parser,
so an argument that does not exist, or one in the wrong position, fails here instead of at
03:00 ICT.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

from app.persistence.cli import build_parser

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_CLI = "python -m app.persistence.cli"
# Shell expansions the parser cannot see through; any concrete value parses the same.
_PLACEHOLDER = {"${SYMBOLS:-$DEFAULT_SYMBOLS}": "HPG,VPB", "$INGEST_URL": "https://example/ingest"}


def _invocations() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                script = step.get("run") or ""
                if _CLI not in script:
                    continue
                # Rejoin line continuations, then take the command itself.
                flat = re.sub(r"\\\s*\n\s*", " ", script)
                for line in flat.splitlines():
                    if _CLI in line:
                        found.append((path.name, line.strip()))
    return found


def test_the_repository_actually_runs_the_cli_from_a_workflow():
    """A guard on the guard: if the invocation is renamed away, this file silently stops
    testing anything, and the next mis-typed flag ships again."""
    assert _invocations(), f"no `{_CLI}` invocation found under {WORKFLOWS}"


@pytest.mark.parametrize("workflow,command", _invocations(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_workflow_cli_invocation_parses(workflow: str, command: str):
    argv = shlex.split(command)[3:]  # drop: python -m app.persistence.cli
    argv = [_PLACEHOLDER.get(token, token) for token in argv]
    # argparse exits 2 on a bad argument instead of raising something catchable.
    args = build_parser().parse_args(argv)
    assert args.command, f"{workflow}: parsed no subcommand from {command!r}"
