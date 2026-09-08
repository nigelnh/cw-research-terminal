"""Thread-local SDK output capture; overlapping calls cannot swap global redirects."""
from __future__ import annotations
import contextlib
import io
import sys
import threading
from app.market_data.feed_status import redact_provider_text

_local = threading.local()
_lock = threading.Lock()


class _Output:
    def __init__(self, original):
        self.original = original

    def write(self, text):
        captures = getattr(_local, "captures", [])
        if captures:
            # Outer gateway observes silent SDK errors even when an inner parser captures.
            for capture in captures:
                capture.write(text)
            return len(text)
        return self.original.write(redact_provider_text(text))

    def flush(self):
        self.original.flush()

    def __getattr__(self, name):
        return getattr(self.original, name)


@contextlib.contextmanager
def capture_sdk_output(output=None):
    with _lock:
        if not isinstance(sys.stdout, _Output):
            sys.stdout = _Output(sys.stdout)
        if not isinstance(sys.stderr, _Output):
            sys.stderr = _Output(sys.stderr)
    capture = output if output is not None else io.StringIO()
    captures = getattr(_local, "captures", [])
    _local.captures = [*captures, capture]
    try:
        yield capture
    finally:
        _local.captures = captures
