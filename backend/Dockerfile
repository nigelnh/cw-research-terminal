# CW Research Terminal — backend (FastAPI, single Uvicorn worker).
#
# IMPORTANT: exactly ONE process / ONE worker in production. VnstockProvider owns
# the shared polling budget and in-memory market state; a second worker would duplicate
# upstream requests against the same account allowance.
# See STEP 11 §1 and DEPLOYMENT.md.

FROM python:3.13-slim AS base

# - PYTHONUNBUFFERED: logs go straight to stdout/stderr (Railway captures these)
# - PIP_NO_CACHE_DIR: smaller image
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime libs: libgomp1 is required by numerical-analysis wheels. No compilers are
# needed because every dependency ships a manylinux wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependency layer — cached until requirements.txt changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Application code (see .dockerignore — no .env, no tests, no __pycache__).
COPY . .

RUN chmod +x /app/entrypoint.sh \
    && adduser --disabled-password --gecos "" --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Railway injects PORT. Local default matches the app's own default.
ENV PORT=8501
EXPOSE 8501

# The entrypoint runs Alembic (idempotent) then exec's Uvicorn so it becomes PID 1
# and receives SIGTERM directly for a graceful provider shutdown.
ENTRYPOINT ["/app/entrypoint.sh"]
