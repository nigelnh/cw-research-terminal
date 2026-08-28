"""Pure-unit tests for the ingestion CLI argument parser (no DB, no provider)."""

from __future__ import annotations

import pytest

from app.persistence.cli import build_parser


def test_parser_accepts_documented_commands():
    p = build_parser()

    ns = p.parse_args([
        "backfill", "--symbols", "HPG,FPT", "--timeframe", "1D",
        "--from", "2026-01-01", "--to", "2026-08-01", "--adjusted", "--dry-run",
    ])
    assert ns.command == "backfill"
    assert ns.symbols == ["HPG", "FPT"]
    assert ns.adjusted is True and ns.dry_run is True and ns.force is False

    ns = p.parse_args(["incremental", "--symbols", "CHPG2602", "--raw"])
    assert ns.command == "incremental" and ns.adjusted is False

    ns = p.parse_args(["gaps", "--symbol", "HPG", "--timeframe", "1D"])
    assert ns.command == "gaps" and ns.adjusted is True

    ns = p.parse_args(["repair", "--symbol", "HPG", "--from", "2026-01-01", "--include-unknown"])
    assert ns.command == "repair" and ns.include_unknown is True

    ns = p.parse_args(["status", "--symbols", "HPG"])
    assert ns.command == "status"

    for cmd in ("seed-instruments", "recent-runs"):
        assert p.parse_args([cmd]).command == cmd


def test_parser_symbol_splitting_normalizes():
    ns = build_parser().parse_args(["status", "--symbols", " hpg , fpt  ssi "])
    assert ns.symbols == ["HPG", "FPT", "SSI"]


def test_parser_rejects_unknown_command_and_missing_required():
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["frobnicate"])
    with pytest.raises(SystemExit):
        p.parse_args(["backfill", "--symbols", "HPG"])  # missing --from
