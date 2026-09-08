# Vnstock migration and acceptance

Date: 2026-09-08

## Result

The terminal runtime now selects `VnstockProvider` exclusively. The provider factory
rejects `MARKET_DATA_PROVIDER=fiinquant`, the public provider package exports Vnstock,
and the production dependency list no longer installs FiinQuant or SignalR packages.

Vnstock Community is a polling HTTP source. It is suitable for this research terminal's
five-second quote cadence, but it is not an exchange-grade push feed and has no realtime
SLA in the public package.

The API key is stored outside the repository in `~/.vnstock/api_key.json` with owner-only
permissions. It is never returned through the terminal API or written to logs. A deployed
container must receive `VNSTOCK_API_KEY` as a secret.

## Entitlement and installation

The official verification endpoint returned:

- `userType=free`
- `hasActiveSubscription=true`
- `availablePackages=[]`

The environment therefore has access to the Community package and free skills, but no
sponsor package artifact is authorized. Installed in `backend/.venv`:

- `vnstock==4.0.7`
- `vnai==2.5.9`

`vnstock_data`, `vnstock_ta`, and `vnstock_news` were not installed because the account
did not receive those packages. `pip check` reports no broken requirements.

Do not install `vnstock_installer` from the public PyPI index. During onboarding, an
unrelated `vnstock_installer==99.0.0` package could win resolution when the sponsor index
was supplied as an extra index. It was not executed and was removed immediately. Use the
official Vnstock installer artifact or a direct authenticated package URL supplied by
Vnstock when sponsor access appears in `availablePackages`.

## Runtime design

- One backend-owned poller batches the current symbol universe. Browser count does not
  multiply upstream traffic.
- A global request floor of 1.2 seconds caps the adapter below 50 calls/minute, leaving
  room under the documented Community allowance of 60 calls/minute.
- Quotes use KBS price-board observations every five seconds. Tape reads are round-robin
  and sweep the subscribed universe every 120 seconds.
- All synchronous library calls run through `asyncio.to_thread`, a concurrency bound, and
  the same request-rate gate.
- Late responses are rejected by subscription generation. Quote, book, history, reference,
  tape, overview group, and each index history call retain separate error scopes.
- The adapter disables Vnstock's automatic agent-file injection before importing the
  package. Importing the runtime cannot create or modify repository/global `AGENTS.md`,
  `.cursorrules`, or similar files.

## Data contract

| Area | Provider path | Terminal contract |
|---|---|---|
| Quote/book | KBS price board | Raw VND, provider session date and observation time |
| REF/bands | KBS price board | Accepted only when its session matches the requested session; fields remain independent |
| CW history | KBS history | Raw VND, `priceBasis=RAW`, explicit completion and provenance |
| Equity raw history | KBS history | Raw VND, `priceBasis=RAW` |
| Equity adjusted daily | VCI history | Rescaled to VND, `priceBasis=ADJUSTED`, excluded from raw spot paths |
| Index history | VCI history | Index points, per-index session and provenance |
| Tape | KBS intraday | Real prints only; dedup includes session, time, price, size, cumulative volume and provider id |
| Fundamentals | VCI ratio summary | Latest reported period plus available P/E, P/B, margin, ROE, ROA, ROIC and gross margin |

Vnstock can return warm-up bars before `from_date`; the adapter filters every historical
response to the exact requested date range and sorts it before returning. KBS history and
tape divide non-index prices by 1,000, so the adapter rescales them once at the provider
boundary. Price-board values are already raw VND and are not rescaled.

Polling snapshots are marked as session observations and do not create fake trade prints.
Confirmed tape events use a separate `trade_print` path so an older print can enter the
tape without rolling the latest quote, live bar, or quant state backward.

## Finding-to-fix matrix

| Finding | Cause | Fix | Evidence |
|---|---|---|---|
| FiinQuant auth/entitlement failure stops data | Runtime constructed FiinQuant directly | Vnstock-only factory and dependencies | Factory rejection test; full backend suite |
| Board/history prices disagree by 1,000x | Vnstock explorers use different units | Normalize at provider boundary by asset/path | Unit tests plus live CW/equity probes |
| REF can be accepted for the wrong day | Board response was not tied to requested session | Exact `session_date` gate and provenance | Wrong-session reference/snapshot tests |
| Duplicate REST reads consume quota | Quote/reference/snapshot can request the same board | Shared recent-board cache, lock and bounded batches | Coalescing test |
| Daily history leaks rows outside request | VCI returns warm-up prefix rows | Exact inclusive range filter and stable sort | Regression test plus live 07–08/09 probe |
| Daily bar can fabricate tape | Board cumulative snapshot resembles a trade | Dedicated confirmed-print event type | Tape normalization and quote rollback tests |
| Same-second trades can collide | Wrapper timestamps can lose subsecond precision | Full print footprint includes cumulative volume | Two same-second print regression test |
| One overview dataset erases all cards | Shared error scope/monolithic refresh | Scope by group/index and build partial result | Isolated overview failure test and live probe |
| Optional overview failures trigger a feed-wide header | Two failures from the same constituent endpoint looked like independent outage evidence | Keep optional group errors in panel datasets and exclude them from banner promotion | Feed-status promotion regression test and browser acceptance |
| Prior-session data looks live after rollover | Freshness used request age only | Require current display session for `feed_fresh` | Previous-session health regression test |
| Quote provenance reports midnight | Session date was parsed before the explicit observation timestamp | Prefer `Timestamp` for `asOf`; retain `TradingDate` as the session and fallback only | Trade/book timestamp regression test and live API/browser check |
| API key presence looks like login success | Legacy `authenticated` field conflated configuration and auth | Report polling mode/key configuration separately; public source has no login session | Health contract tests |
| Package import edits agent config files | Vnstock starts agent bootstrap in the background | Set supported disable flags before first import | Environment regression test and clean worktree check |
| EOD missing-leg test changes with local network | Global gap-fill could answer during an integration test | Explicit unavailable upstream fixture | PostgreSQL EOD alignment tests |

## Live acceptance evidence

Read-only probes from this environment completed with no provider failures:

- `CHPG2625` quote session `2026-09-08`: last 540 VND, REF 550 VND, bid/ask 540/560 VND.
- CW history returned raw close 540 VND from `VNSTOCK_KBS`.
- HPG adjusted daily history returned close 21,850 VND from `VNSTOCK_VCI`.
- Twenty confirmed CW prints traversed the separate tape path.
- VN30 and VNINDEX returned current value, previous-session reference, 47 five-minute
  points, and complete constituent breadth (30/30 and 405/405).
- VCI returned index prices for VNFINLEAD and VNDIAMOND but its current constituent-group
  endpoint returned no usable list. Those two cards remain `PARTIAL` with
  `BREADTH_UNAVAILABLE`; other indices and leaderboards remain available.

This proves current endpoint behavior and adapter normalization. It does not establish an
upstream SLA or redistribution rights.

## Validation

- Backend: `1520 passed, 20 skipped`
- Focused Vnstock provider tests: `14 passed`
- Frontend: `450 passed`
- TypeScript and production Vite build: passed
- Pyright on new provider/factory/normalizer: 0 errors
- Ruff on new provider/factory/normalizer/tests: passed
- Dependency validation: `pip check` passed
- Browser: Watchlist, STATS, QUANT, daily RAW chart and AI instrument context passed;
  no console warnings/errors

The repository-wide Pyright/Ruff configurations currently report pre-existing issues in
unrelated files; the new provider boundary is clean under both tools.

## Local and production setup

```bash
cd backend
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

For local use, register the key through Vnstock's official helper or keep the existing
owner-only `~/.vnstock/api_key.json`. For deployment, set these server-side secrets/config:

```text
MARKET_DATA_PROVIDER=vnstock
VNSTOCK_API_KEY=<secret>
VNSTOCK_QUOTE_POLL_SECONDS=5
VNSTOCK_TAPE_SWEEP_SECONDS=120
VNSTOCK_TAPE_PAGE_SIZE=100
VNSTOCK_MIN_REQUEST_INTERVAL_SECONDS=1.2
MARKET_DATA_MAX_SYMBOLS=60
```

The package metadata states a personal/research/non-commercial license. Confirm a suitable
license and source-data display rights before commercial or public redistribution.

## Skill access

The current free tier catalog exposes these skills:

- `charting-expert`
- `news-crawler`
- `pipeline-cli`
- `solution-architect`
- `vnstock-bootstrap`
- `migration-assistant`

Silver skills are `macro-analyzer`, `market-screener`, and `indicator-calculator`; Golden
and Diamond skills require a higher tier. Catalog visibility does not grant access.

Load a skill only in process memory:

```python
import os

os.environ["VNSTOCK_DISABLE_AGENT_SETUP"] = "1"
os.environ["VNSTOCK_DISABLE_GLOBAL_AGENT"] = "1"

from vnstock.core.utils.agents import load_skill, load_skill_catalog

catalog = load_skill_catalog()
content = load_skill("solution-architect", "content")
```

Do not dump skill content/configuration to disk. `load_skill` returns `None` and reports a
403 when the key does not have the required tier.

## Sources

- [Vnstock onboarding](https://vnstocks.com/files/vibe-onboarding.md)
- [Vnstock repository](https://github.com/thinh-vu/vnstock)
- [Vnstock license](https://github.com/thinh-vu/vnstock/blob/main/LICENSE.md)
- [Vnstock on PyPI](https://pypi.org/project/vnstock/)
