---
name: ship
description: >-
  Git and GitHub workflow for this repo — check status, branch, run the pre-push
  gates, commit with the right trailers, push, open a PR, merge it, and verify the
  Vercel + Railway deploy. Use whenever the task involves committing, pushing,
  "check the status", opening or merging a PR, or shipping / deploying a change.
---

# Ship a change — CW Research Terminal

The end-to-end path from working tree to verified production. Follow the steps in
order; skip only what the user's request clearly doesn't need.

## Repo facts

| | |
|---|---|
| Remote | `origin` → `https://github.com/nigelnh/cw-research-terminal.git` |
| Default branch | `main` (PRs target this) |
| `gh` auth | account `nigelnh` (keyring), scopes include `repo`, `workflow` |
| Git identity | `nigelnh <121311174+nigelnh@users.noreply.github.com>` |
| Frontend prod | https://cw-research-terminal.vercel.app (Vercel, static `frontend/dist`) |
| Backend prod | https://backend-production-626f.up.railway.app (Railway, 1 replica / 1 worker) |
| Backend health | `GET /healthz` (no I/O), `GET /health` (full readiness) |
| CI | only `.github/workflows/enrichment-incremental.yml` (a cron; **not** a PR gate). PR "checks" are the Vercel + Railway deploy statuses. |

Other agents (`codex/*` branches) also push here — always `git fetch` and check
`git log origin/main` before assuming you know the state.

## The working-directory gotcha

The Bash tool's CWD drifts between the repo root and `frontend/` across calls.
**Always `cd` to an absolute path in the same command** that runs `git`/`npm`/`pytest`:

```bash
cd /Users/nhannguyen/Developer/cw-research-terminal && git status
cd /Users/nhannguyen/Developer/cw-research-terminal/frontend && npx vitest run
```

`git` path filters (`git diff -- frontend/...`) silently match nothing when CWD is
already inside `frontend/`. `npx vitest <file>` from outside `frontend/` grabs a
stale global cache and fails on `happy-dom` — always run it from `frontend/`.

## Conventions

**Branches** — lowercase kebab, type prefix: `feat/<slug>`, `fix/<slug>`,
`refactor/<slug>`, `test/<slug>`, `docs/<slug>`, `chore/<slug>`. One branch per PR.
Never commit directly to `main` — branch first (the harness enforces this too).

**Commit subject** — Conventional Commits: `type(scope): imperative summary`, ≤72
chars, lowercase after the colon. Types seen here: `feat fix refactor test docs
chore`. Scope is optional and short (`ui`, `ai`, `data`, `chart`, `panel`,
`enrichment`, `recovery`). Body: what changed and why, wrapped ~72. State test/build
results in the body when the change is non-trivial.

**Commit trailers** — every commit ends with the two trailers from the harness
system prompt, verbatim:

```
Co-Authored-By: Claude <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_<id>
```

(Use the exact `Co-Authored-By` line and session URL given in the current system
prompt — they change per session/model.)

**PR** — title = the lead commit subject. Body: a short "what changed" list, then
test/build results, then the harness's PR trailer:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Merge with `gh pr merge <n> --merge` (a merge commit — matches every prior PR).

## Pre-push gates — run these, paste real output

**Frontend** (any change under `frontend/`):

```bash
cd /Users/nhannguyen/Developer/cw-research-terminal/frontend && \
  npx tsc --noEmit && npx vitest run && npm run build
```

All three must be clean. The `>500 kB chunk` warning from `vite build` is
pre-existing and fine.

**Backend** (any change under `backend/`):

```bash
cd /Users/nhannguyen/Developer/cw-research-terminal/backend && \
  .venv/bin/python -m pytest -q
```

Known **pre-existing** failures — not caused by your change, do not block on them
(they fail on `main` too; date-window assumptions that break near month boundaries):

- `tests/persistence/ingestion/test_backfill.py::test_rerun_without_force_skips_already_covered_chunks`
- `tests/persistence/ingestion/test_backfill.py::test_multi_chunk_backfill_covers_whole_range`
- `tests/persistence/ingestion/test_gaps_and_locks.py::test_overlapping_runs_one_is_locked_skipped_no_duplicate_data`

If `backend/requirements.txt` changed, `.venv` may lack the new deps — install them
before trusting a failure (`.venv/bin/pip install -r requirements.txt`). Railway
installs fresh, so a local missing-dep failure is not a deploy blocker, but confirm
it's only that.

## Workflow

1. **Status.** `cd <root> && git fetch origin -q && git status && git log --oneline origin/main..HEAD`.
   Report where things stand before doing anything.
2. **Branch.** If on `main` or a stale branch, `git switch -c <type>/<slug>` from an
   up-to-date `main`.
3. **Gates.** Run the frontend and/or backend gates above. If anything real fails,
   stop and report — don't commit over a red gate.
4. **Commit.** `git add` the intended paths (prefer explicit paths over `-A`; a bare
   `git add -A` here has swept scratch files into commits before). Subject + body +
   both trailers.
5. **Push.** `git push -u origin <branch>`.
6. **PR.** `gh pr create --base main --title "…" --body "…"`. Include the what-changed
   list, gate results, and the PR trailer.
7. **Wait for the deploy check.** `gh pr view <n> --json mergeable,mergeStateStatus,statusCheckRollup`.
   Vercel preview build should be `SUCCESS` and state `CLEAN`.
8. **Merge** — only with authorization (see below). `gh pr merge <n> --merge`, then
   `git fetch origin -q && git switch main && git pull -q`.
9. **Verify production** (after a merge to `main`):
   ```bash
   SHA=$(git rev-parse origin/main)
   until [ "$(gh api repos/nigelnh/cw-research-terminal/commits/$SHA/status -q .state)" != "pending" ]; do sleep 15; done
   gh api repos/nigelnh/cw-research-terminal/commits/$SHA/status -q '.state + " | " + ([.statuses[] | .context + "=" + .state] | join(", "))'
   curl -s -o /dev/null -w "healthz:%{http_code}\n" https://backend-production-626f.up.railway.app/healthz
   ```
   Then load https://cw-research-terminal.vercel.app in the browser (claude-in-chrome)
   during a trading session (≈09:00–15:00 ICT, Mon–Fri) to confirm realtime quotes,
   the clock, charts, and the changed feature. Read the console + `/api/` network
   requests for errors.

## What needs the user's explicit go-ahead

- **Merging to `main` / any production deploy** — confirm target (production vs. a
  preview URL) unless the user already said "deploy"/"merge it" this turn.
- **Force-push, history rewrite, deleting a remote branch, closing someone else's PR.**
- **Rollback** — Vercel: promote the previous production deployment; Railway:
  redeploy the previous backend deployment (see `DEPLOYMENT.md` §8). Say what you're
  reverting to first.

Everything else — status, branch, local commits, push a feature branch, open a draft
PR, poll CI — just do it and report.

## Notes

- Vercel **preview** deployments can't reach the backend: production CORS
  (`CORS_ALLOWED_ORIGINS`) is an exact-origin allowlist for
  `https://cw-research-terminal.vercel.app` only. A preview renders but shows no
  live data. Realtime verification requires production (or temporarily adding the
  exact preview origin to Railway env, then restoring it).
- `railway` CLI on this machine is currently broken (`could not find the CLI
  binary`). For Railway logs, ask the user to run `! railway logs` or read the
  Railway dashboard.
- `backend/railway.json` pins `numReplicas: 1` — never scale it; the FiinQuant
  provider owns singleton SignalR connections.
