"""Sanitized provider access evidence, separate from transport connectivity."""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any


MESSAGES = {
    "ENTITLEMENT_EXPIRED": "Market data access has expired. The data provider account needs renewal.",
    "AUTH_REQUIRED": "Market data provider authentication is unavailable.",
    "DATASET_FORBIDDEN": "This dataset is not available under the provider account's permissions.",
    "RATE_LIMITED": "The market data provider is rate limiting requests.",
    "UPSTREAM_UNAVAILABLE": "The market data provider is temporarily unavailable.",
    "AWAITING_DATA": "Awaiting market observations for this session.",
    "STALE": "Market data updates are delayed. Displayed observations retain their original time.",
    "AVAILABLE": "Market data is available.",
    "SESSION_PAUSED": "Matching is paused or the market is closed.",
}


#: HTTP status codes must match as whole tokens. This classifier is fed CAPTURED SDK
#: STDOUT, which is full of tickers, prices and volumes - a bare substring test read
#: "no bars for HPG at 21500" as a 500 and "volume 1403000" as a 403, and a false
#: DATASET_FORBIDDEN blocks that scope for a quarter of an hour.
_STATUS = re.compile(r"(?<!\d)(401|403|429|500|502|503|504)(?!\d)")

#: A bare number is only a status code in text that is reporting a failure. Without this,
#: "fetched 429 rows for CVPB2611" reads as a rate limit. The textual markers below carry
#: nearly every real case on their own; the numeric path is a backstop, not the primary
#: signal, so narrowing it costs little and removes a whole class of false positives.
_FAILURE_CONTEXT = (
    "error", "fail", "exception", "denied", "refused", "unauthor", "forbidden",
    "status", "http", "message=", "url=", "circuit", "limit",
)


def classify_provider_error(value: Any) -> str | None:
    text = str(value).lower()
    codes = set(_STATUS.findall(text)) if any(m in text for m in _FAILURE_CONTEXT) else set()
    if any(s in text for s in ("service has expired", "subscription has expired", "entitlement_expired")):
        return "ENTITLEMENT_EXPIRED"
    if "401" in codes or any(s in text for s in ("unauthorized", "invalid_token", "invalid_grant", "auth_required")):
        return "AUTH_REQUIRED"
    if "403" in codes or any(s in text for s in ("forbidden", "permission to access", "dataset_forbidden")):
        return "DATASET_FORBIDDEN"
    if "429" in codes or any(s in text for s in ("ratelimit", "rate limit")):
        return "RATE_LIMITED"
    if codes & {"500", "502", "503", "504"} or any(
        s in text for s in ("timeout", "connection error", "upstream_unavailable")
    ):
        return "UPSTREAM_UNAVAILABLE"
    return None


def redact_provider_text(value: Any) -> str:
    text = str(value)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "[redacted]", text)
    return re.sub(r"(?i)(bearer\s+|(?:access_token|password|authorization)[\s\"':=]+)[^\s,}]+", r"\1[redacted]", text)


class FeedAccess:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._errors: dict[str, dict] = {}

    def record(self, scope: str, error: Any) -> str | None:
        code = classify_provider_error(error)
        if code is None:
            return None
        if code == "ENTITLEMENT_EXPIRED":
            scope = "market_data"
        elif code == "AUTH_REQUIRED":
            scope = "authentication"
        with self._lock:
            self._errors[scope] = {
                "code": code, "scope": scope, "message": MESSAGES[code],
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "retryAt": time.monotonic() + (900 if code in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN") else 60),
            }
        return code

    def inspect_session(self, session: Any) -> None:
        # These claims are diagnostic evidence, never an authorization decision or a
        # browser payload. A valid login token does not prove dataset entitlement.
        token = getattr(session, "access_token", None)
        if not isinstance(token, str):
            return
        try:
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            end = datetime.strptime(claims["end_date"], "%d/%m/%Y").date()
            from app.market_data.trading_calendar import _as_vn
            if end < _as_vn(None).date():
                self.record("market_data", "ENTITLEMENT_EXPIRED")
        except (ValueError, KeyError, IndexError, TypeError):
            pass

    def retry_after(self, scope: str) -> float:
        with self._lock:
            return max([0.0] + [self._errors[k]["retryAt"] - time.monotonic()
                              for k in ("market_data", "authentication", scope) if k in self._errors])

    def blocked(self, scope: str) -> str | None:
        with self._lock:
            for key in ("market_data", "authentication", scope):
                err = self._errors.get(key)
                if err and err["retryAt"] > time.monotonic():
                    return err["code"]
        return None

    def success(self, scope: str) -> None:
        with self._lock:
            self._errors.pop(scope, None)
            if scope in ("history", "overview", "session_snapshot", "stream"):
                self._errors.pop("market_data", None)
                self._errors.pop("authentication", None)

    def wire(self, *, fresh: bool, active: bool, last_data_at: str | None) -> dict:
        with self._lock:
            errors = [{k: v for k, v in err.items() if k != "retryAt"} for err in self._errors.values()]
        global_error = next((e for e in errors if e["scope"] in ("market_data", "authentication")), None)
        code = "AVAILABLE" if fresh else "SESSION_PAUSED" if not active else "STALE" if last_data_at else "AWAITING_DATA"
        return {
            **(global_error or {"code": code, "scope": "market_data", "message": MESSAGES[code],
                               "checkedAt": datetime.now(timezone.utc).isoformat()}),
            "lastDataAt": last_data_at,
            "datasets": errors,
        }
