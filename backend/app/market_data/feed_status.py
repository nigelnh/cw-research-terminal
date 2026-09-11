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
    # States what was observed, and stops there. An earlier wording said the account
    # "needs renewal", which was a guess about the provider's product: the evidence only
    # shows that the entitlement window ended and that logging in again does not extend it.
    # What restores access is FiinQuant's business, not something this server can know, and
    # a header that prescribes the wrong remedy is worse than one that reports the fact.
    "ENTITLEMENT_EXPIRED": "Market data access is not active for this provider account.",
    "AUTH_REQUIRED": "Market data provider authentication is unavailable.",
    "DATASET_FORBIDDEN": "This dataset is not available under the provider account's permissions.",
    "RATE_LIMITED": "The market data provider is rate limiting requests.",
    "UPSTREAM_UNAVAILABLE": "The market data provider is temporarily unavailable.",
    "AWAITING_DATA": "Awaiting market observations for this session.",
    "STALE": "Market data updates are delayed. Displayed observations retain their original time.",
    "AVAILABLE": "Market data is available.",
    "SESSION_PAUSED": "Matching is paused or the market is closed.",
}

# Failures below these prefixes describe optional components of one composite
# response.  Two index groups failing the same VCI constituent endpoint are not
# two independent observations that the whole market-data provider is down.
# They remain in ``datasets`` so the owning cards can disclose partial coverage.
_BANNER_PROMOTION_EXCLUDED_PREFIXES = ("overview_group_",)


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
        #: Diagnostic only. Explains a real rejection; never causes one.
        self._entitlement_note: str | None = None

    def record(self, scope: str, error: Any, *, detail: str | None = None) -> str | None:
        code = classify_provider_error(error)
        if code is None:
            return None
        # The failure stays in the scope that produced it. Promoting it to a feed-wide
        # key was how ONE endpoint took the whole terminal down: `get_ceilingfloor`
        # returned 401 (it serves stocks only, never covered warrants), that was rewritten
        # to scope "authentication", and `blocked()` consults that key for every other
        # scope - so the realtime tick stream, which had just subscribed 30 symbols
        # successfully, was refused on the strength of an unrelated REST endpoint.
        #
        # A genuine login failure is already recorded under "authentication" by the
        # `_sdk_call("authentication", ...)` that wraps session creation, and that one
        # SHOULD be feed-wide. Nothing else earns that.
        with self._lock:
            message = MESSAGES[code]
            note = detail or (self._entitlement_note if code == "ENTITLEMENT_EXPIRED" else None)
            if note:
                message = f"{message} {note}"
            self._errors[scope] = {
                "code": code, "scope": scope, "message": message,
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "retryAt": time.monotonic() + (900 if code in ("ENTITLEMENT_EXPIRED", "DATASET_FORBIDDEN") else 60),
            }
        return code

    def inspect_session(self, session: Any) -> None:
        """Record what the token CLAIMS about entitlement. Never blocks anything.

        This used to call `record()`, which meant a date field in a JWT became an
        authorization decision: `blocked()` gates every SDK call and the stream startup, so
        the app stopped talking to the provider entirely without a single request having
        been refused. That is the opposite of the rule this module was written for - only
        the provider gets to say no, and it says so by rejecting a call.

        It also made the diagnosis unfalsifiable. With the stream never attempting to
        connect, there was no way to tell an expired entitlement from any other reason a
        connection might fail, because no connection was ever made.
        """
        token = getattr(session, "access_token", None)
        if not isinstance(token, str):
            return
        try:
            part = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            end = datetime.strptime(claims["end_date"], "%d/%m/%Y").date()
            from app.market_data.trading_calendar import _as_vn
            with self._lock:
                # The date is the one fact that makes a later rejection actionable, and it
                # is not sensitive. No other claim from the token is kept.
                self._entitlement_note = (
                    f"Access ended {end.isoformat()}." if end < _as_vn(None).date() else None
                )
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
        promotion_errors = [
            error for error in errors
            if not error["scope"].startswith(_BANNER_PROMOTION_EXCLUDED_PREFIXES)
        ]
        if global_error is None and not fresh and len(promotion_errors) > 1:
            # An account-wide condition is DISCOVERED, never assumed: when several
            # independent scopes are rejected the same way, that is the feed talking, not
            # one endpoint. A single failure only ever speaks for itself - `get_ceilingfloor`
            # is 401 for this account by design and must not headline as an auth outage.
            # A fresh realtime stream is stronger current evidence than old failures from
            # optional REST datasets. Those failures remain in ``datasets`` for their
            # owning panels, but they cannot turn a healthy live board into a global outage.
            # This affects the banner only; blocking stays strictly per scope.
            counts: dict[str, int] = {}
            for err in promotion_errors:
                counts[err["code"]] = counts.get(err["code"], 0) + 1
            worst, seen = max(counts.items(), key=lambda kv: kv[1])
            if seen > 1:
                global_error = next(e for e in promotion_errors if e["code"] == worst)
        code = "AVAILABLE" if fresh else "SESSION_PAUSED" if not active else "STALE" if last_data_at else "AWAITING_DATA"
        return {
            **(global_error or {"code": code, "scope": "market_data", "message": MESSAGES[code],
                               "checkedAt": datetime.now(timezone.utc).isoformat()}),
            "lastDataAt": last_data_at,
            "datasets": errors,
        }
