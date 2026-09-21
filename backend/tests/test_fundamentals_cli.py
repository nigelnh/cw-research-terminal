"""`app.persistence.cli fundamentals` is actually executed here.

It shipped twice broken, and neither break was reachable from the suite. First `--json`
sat after the subcommand, so argparse exited 2. Then the body referenced `timezone`
without importing it:

    observed = datetime.now(timezone.utc)
    NameError: name 'timezone' is not defined

Both were only discoverable by running the scheduled workflow - checkout, 41s of pip
install, then a crash. The read path had tests and the argv had a parse guard, but nothing
ever ran the function, so any name error, wrong keyword or bad payload shape inside it
reached production unchallenged.

These drive the whole command with a fake provider and a fake transport. No network, no
database, no sleeping.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.persistence.cli import _cmd_fundamentals, build_parser

VALUATION = {"symbol": "HPG", "pe": 7.9, "pb": 1.3, "as_of": "2026Q2"}
QUARTERS = [{"period": "2026Q2", "roe": 0.21, "statement_source": "VNSTOCK_VCI_INCOME_STATEMENT"}]


class _FakeProvider:
    def __init__(self, data: dict, raises: set[str] | None = None):
        self.data, self.raises = data, raises or set()
        self.seen: list[str] = []

    async def get_stock_valuation(self, symbols):
        sym = symbols[0]
        self.seen.append(sym)
        if sym in self.raises:
            raise RuntimeError("403 - Forbidden")
        return {sym: self.data.get(sym, {}).get("valuation", {})}

    async def get_financial_ratios(self, symbol):
        if symbol in self.raises:
            raise RuntimeError("403 - Forbidden")
        return self.data.get(symbol, {}).get("quarters", [])


class _FakeResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code, self.text = status_code, text


class _FakeHttpClient:
    """Captures the one POST the command makes."""

    calls: list[dict] = []
    status = 200
    body = "ok"

    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

    async def post(self, url, json=None, headers=None):
        type(self).calls.append({"url": url, "json": json, "headers": headers or {}})
        return _FakeResponse(type(self).status, type(self).body)


def _args(symbols: str, **over):
    argv = ["--json", "fundamentals", "--symbols", symbols,
            "--api-url", "https://backend.example/api/market/fundamentals/ingest"]
    args = build_parser().parse_args(argv)
    args.delay = 0.0
    for k, v in over.items():
        setattr(args, k, v)
    return args


def _run(args, provider, token="tok", printed=None):
    _FakeHttpClient.calls = []
    _FakeHttpClient.status, _FakeHttpClient.body = 200, "ok"
    with patch("app.market_data.providers.provider_factory.create_market_provider",
               return_value=provider), \
         patch("httpx.AsyncClient", _FakeHttpClient), \
         patch.dict("os.environ", {"FUNDAMENTALS_INGEST_TOKEN": token}, clear=False):
        return asyncio.run(_cmd_fundamentals(args))


def test_the_command_runs_end_to_end_and_posts_what_it_fetched(capsys):
    provider = _FakeProvider({"HPG": {"valuation": VALUATION, "quarters": QUARTERS}})
    code = _run(_args("HPG"), provider)

    assert code == 0
    assert len(_FakeHttpClient.calls) == 1
    call = _FakeHttpClient.calls[0]
    item = call["json"]["items"][0]
    assert item["symbol"] == "HPG"
    assert item["valuation"] == VALUATION
    assert item["quarters"] == QUARTERS
    assert item["observed_at"]  # the line that raised NameError in production
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert json.loads(capsys.readouterr().out)["written"] == ["HPG"]


def test_a_symbol_with_nothing_to_say_is_never_posted():
    """The shape a 403 leaves behind. Posting it would overwrite a good stored row."""
    provider = _FakeProvider({"HPG": {"valuation": VALUATION, "quarters": QUARTERS},
                              "VPB": {"valuation": {}, "quarters": []}})
    code = _run(_args("HPG,VPB"), provider)

    assert code == 0
    posted = [i["symbol"] for i in _FakeHttpClient.calls[0]["json"]["items"]]
    assert posted == ["HPG"], "an empty result must not reach the ingest route"


def test_one_failing_symbol_does_not_end_the_run(capsys):
    provider = _FakeProvider({"HPG": {"valuation": VALUATION, "quarters": QUARTERS}},
                             raises={"VPB"})
    code = _run(_args("HPG,VPB"), provider)
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["written"] == ["HPG"]
    assert "VPB" in report["failed"]
    assert [i["symbol"] for i in _FakeHttpClient.calls[0]["json"]["items"]] == ["HPG"]


def test_writing_nothing_at_all_fails_the_scheduled_run():
    """A few illiquid symbols with no statements is normal; every symbol failing is an
    egress problem the schedule must go red for."""
    provider = _FakeProvider({}, raises={"HPG", "VPB"})
    assert _run(_args("HPG,VPB"), provider) == 1
    assert _FakeHttpClient.calls == []


def test_a_missing_token_is_refused_before_anything_is_sent():
    provider = _FakeProvider({"HPG": {"valuation": VALUATION, "quarters": QUARTERS}})
    with pytest.raises(RuntimeError, match="FUNDAMENTALS_INGEST_TOKEN"):
        _run(_args("HPG"), provider, token="")
    assert _FakeHttpClient.calls == []


def test_a_rejected_ingest_surfaces_the_status_without_echoing_the_token():
    provider = _FakeProvider({"HPG": {"valuation": VALUATION, "quarters": QUARTERS}})
    _FakeHttpClient.calls = []
    with patch("app.market_data.providers.provider_factory.create_market_provider",
               return_value=provider), \
         patch("httpx.AsyncClient", _FakeHttpClient), \
         patch.dict("os.environ", {"FUNDAMENTALS_INGEST_TOKEN": "sup3r-s3cret"}, clear=False):
        _FakeHttpClient.status, _FakeHttpClient.body = 401, "unauthorized"
        with pytest.raises(RuntimeError) as err:
            asyncio.run(_cmd_fundamentals(_args("HPG")))

    assert "401" in str(err.value)
    assert "sup3r-s3cret" not in str(err.value)
