#!/usr/bin/env sh
# CW Research Terminal — container entrypoint.
#
#   1. Apply DB migrations (idempotent; only when a database is configured).
#   2. exec Uvicorn as PID 1 with a SINGLE worker.
#
# Does NOT run any historical backfill — ingestion is an explicit operational command
# (`python -m app.persistence.cli ...`), never automatic on boot.
set -eu

PORT="${PORT:-8501}"

if [ "${DATABASE_ENABLED:-false}" = "true" ] && [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] Applying Alembic migrations (alembic upgrade head)..."
  alembic upgrade head
  echo "[entrypoint] Migrations applied. Current head:"
  alembic current || true
else
  echo "[entrypoint] DATABASE_ENABLED!=true — skipping migrations."
fi

echo "[entrypoint] Starting Uvicorn (1 worker) on 0.0.0.0:${PORT}"
# --no-proxy-headers: Uvicorn must NOT rewrite conn.client from X-Forwarded-* itself.
# The app resolves the trusted client IP explicitly (app/security/client_ip.py) so the
# rate limiter keys on a value a client cannot spoof.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 1 \
  --timeout-graceful-shutdown 25 \
  --no-server-header \
  --no-proxy-headers
