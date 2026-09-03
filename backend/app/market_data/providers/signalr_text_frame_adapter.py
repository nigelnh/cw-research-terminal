"""Bounded text-frame reassembly for ``signalrcore`` websocket callbacks.

``signalrcore==0.9.71`` assumes that every websocket callback ends at a SignalR
record separator.  Some websocket implementations can instead deliver a text
record in pieces.  This adapter retains only the unfinished suffix and forwards
complete batches to the original ``on_message(app, raw_message)`` callback.

The adapter deliberately has no logging.  Its statistics and error metadata
contain byte counts and error categories, never frame contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any, Callable, Optional


SIGNALR_RECORD_SEPARATOR = "\x1e"
DEFAULT_MAX_BUFFER_BYTES = 1024 * 1024
DEFAULT_PARTIAL_TIMEOUT_SECONDS = 5.0


class SignalRFrameErrorKind(str, Enum):
    """Stable error categories suitable for provider health reporting."""

    PARTIAL_TIMEOUT = "partial_timeout"
    BUFFER_OVERFLOW = "buffer_overflow"
    FRAME_ERROR = "frame_error"


@dataclass(frozen=True)
class SignalRFrameError:
    """Payload-free details about a rejected or failed frame batch."""

    kind: SignalRFrameErrorKind
    occurred_at: float
    buffered_bytes: int
    incoming_bytes: int = 0
    limit_bytes: Optional[int] = None
    partial_age_seconds: Optional[float] = None
    exception_type: Optional[str] = None


@dataclass(frozen=True)
class SignalRFrameFeedResult:
    """Result of one websocket callback without retaining the frame payload."""

    emitted_batches: int = 0
    emitted_frames: int = 0
    error: Optional[SignalRFrameError] = None


@dataclass(frozen=True)
class SignalRFrameBufferStats:
    """Snapshot of adapter counters and current bounded-buffer size."""

    received_chunks: int
    received_bytes: int
    emitted_batches: int
    emitted_frames: int
    emitted_bytes: int
    buffered_bytes: int
    partial_timeouts: int
    buffer_overflows: int
    frame_errors: int
    dropped_bytes: int


OnMessageCallback = Callable[[Any, str], Any]
OnErrorCallback = Callable[[SignalRFrameError], Any]
MonotonicClock = Callable[[], float]


class SignalRTextFrameAdapter:
    """Reassemble SignalR text records before calling a 0.9.71 transport handler.

    ``on_message`` has the same ``(app, raw_message)`` signature as
    ``signalrcore``'s websocket transport callback.  A complete prefix is passed
    to the wrapped callback as one unchanged batch; only the suffix following
    the last record separator is retained.

    Timeout checks happen when a new chunk arrives or when ``expire_partial`` is
    called. Websocket callbacks and the provider's timeout timer can run on
    different threads, so all buffer/counter mutation is serialized. Wrapped
    callbacks are deliberately invoked after releasing the state lock.
    """

    def __init__(
        self,
        on_message: OnMessageCallback,
        *,
        on_error: Optional[OnErrorCallback] = None,
        max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES,
        partial_timeout_seconds: float = DEFAULT_PARTIAL_TIMEOUT_SECONDS,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        if max_buffer_bytes <= 0:
            raise ValueError("max_buffer_bytes must be positive")
        if partial_timeout_seconds <= 0:
            raise ValueError("partial_timeout_seconds must be positive")

        self._on_message = on_message
        self._on_error = on_error
        self._max_buffer_bytes = max_buffer_bytes
        self._partial_timeout_seconds = partial_timeout_seconds
        self._clock = clock
        self._lock = threading.RLock()

        self._buffer = ""
        self._buffered_bytes = 0
        self._partial_started_at: Optional[float] = None

        self._received_chunks = 0
        self._received_bytes = 0
        self._emitted_batches = 0
        self._emitted_frames = 0
        self._emitted_bytes = 0
        self._partial_timeouts = 0
        self._buffer_overflows = 0
        self._frame_errors = 0
        self._dropped_bytes = 0
        self._last_error: Optional[SignalRFrameError] = None

    @property
    def stats(self) -> SignalRFrameBufferStats:
        """Return counters without exposing buffered text."""
        with self._lock:
            return SignalRFrameBufferStats(
                received_chunks=self._received_chunks,
                received_bytes=self._received_bytes,
                emitted_batches=self._emitted_batches,
                emitted_frames=self._emitted_frames,
                emitted_bytes=self._emitted_bytes,
                buffered_bytes=self._buffered_bytes,
                partial_timeouts=self._partial_timeouts,
                buffer_overflows=self._buffer_overflows,
                frame_errors=self._frame_errors,
                dropped_bytes=self._dropped_bytes,
            )

    @property
    def last_error(self) -> Optional[SignalRFrameError]:
        """Return the latest payload-free error metadata, if any."""

        with self._lock:
            return self._last_error

    @property
    def partial_deadline(self) -> Optional[float]:
        """Monotonic deadline for the retained suffix, without exposing its contents."""

        with self._lock:
            if self._partial_started_at is None:
                return None
            return self._partial_started_at + self._partial_timeout_seconds

    def on_message(self, app: Any, raw_message: str) -> SignalRFrameFeedResult:
        """Accept one websocket text chunk and forward any complete batch."""
        now = self._clock()
        complete_batch: Optional[str] = None
        frame_count = 0
        complete_bytes = 0
        error: Optional[SignalRFrameError] = None

        with self._lock:
            self._received_chunks += 1

            if not isinstance(raw_message, str):
                error = SignalRFrameError(
                    kind=SignalRFrameErrorKind.FRAME_ERROR,
                    occurred_at=now,
                    buffered_bytes=self._buffered_bytes,
                    exception_type=type(raw_message).__name__,
                )
                self._frame_errors += 1
                self._record_error_locked(error)
            else:
                incoming_bytes = len(raw_message.encode("utf-8"))
                self._received_bytes += incoming_bytes
                error = self._expire_if_needed_locked(now, incoming_bytes=incoming_bytes)
                if error is not None:
                    # The new chunk may be the tail of the expired partial record.
                    # Drop it as part of the failed batch so malformed JSON is not
                    # passed to signalrcore.
                    self._dropped_bytes += incoming_bytes
                else:
                    combined = self._buffer + raw_message
                    last_separator = combined.rfind(SIGNALR_RECORD_SEPARATOR)
                    if last_separator < 0:
                        combined_bytes = len(combined.encode("utf-8"))
                        if combined_bytes > self._max_buffer_bytes:
                            error = SignalRFrameError(
                                kind=SignalRFrameErrorKind.BUFFER_OVERFLOW,
                                occurred_at=now,
                                buffered_bytes=self._buffered_bytes,
                                incoming_bytes=incoming_bytes,
                                limit_bytes=self._max_buffer_bytes,
                            )
                            self._buffer_overflows += 1
                            self._dropped_bytes += combined_bytes
                            self._clear_partial_locked()
                            self._record_error_locked(error)
                        else:
                            self._buffer = combined
                            self._buffered_bytes = combined_bytes
                            if combined and self._partial_started_at is None:
                                self._partial_started_at = now
                    else:
                        complete_batch = combined[: last_separator + 1]
                        trailing_partial = combined[last_separator + 1 :]
                        trailing_bytes = len(trailing_partial.encode("utf-8"))
                        if trailing_bytes > self._max_buffer_bytes:
                            error = SignalRFrameError(
                                kind=SignalRFrameErrorKind.BUFFER_OVERFLOW,
                                occurred_at=now,
                                buffered_bytes=self._buffered_bytes,
                                incoming_bytes=incoming_bytes,
                                limit_bytes=self._max_buffer_bytes,
                            )
                            self._buffer_overflows += 1
                            self._dropped_bytes += trailing_bytes
                            self._clear_partial_locked()
                            self._record_error_locked(error)
                        else:
                            self._buffer = trailing_partial
                            self._buffered_bytes = trailing_bytes
                            self._partial_started_at = now if trailing_partial else None
                        frame_count = complete_batch.count(SIGNALR_RECORD_SEPARATOR)
                        complete_bytes = len(complete_batch.encode("utf-8"))

        # User/provider callbacks may inspect or reset this adapter, and therefore
        # must never run while its state lock is held.
        if error is not None:
            self._notify_error(error)
        if complete_batch is None:
            return SignalRFrameFeedResult(error=error)

        try:
            self._on_message(app, complete_batch)
        except Exception as exc:  # signalrcore can reject malformed complete JSON
            with self._lock:
                callback_error = SignalRFrameError(
                    kind=SignalRFrameErrorKind.FRAME_ERROR,
                    occurred_at=now,
                    buffered_bytes=self._buffered_bytes,
                    incoming_bytes=len(raw_message.encode("utf-8")),
                    exception_type=type(exc).__name__,
                )
                self._frame_errors += 1
                self._record_error_locked(callback_error)
            self._notify_error(callback_error)
            return SignalRFrameFeedResult(error=callback_error)

        with self._lock:
            self._emitted_batches += 1
            self._emitted_frames += frame_count
            self._emitted_bytes += complete_bytes
        return SignalRFrameFeedResult(
            emitted_batches=1,
            emitted_frames=frame_count,
            error=error,
        )

    feed = on_message

    def expire_partial(self) -> Optional[SignalRFrameError]:
        """Expire a stale suffix, for callers that have a periodic health tick."""
        with self._lock:
            error = self._expire_if_needed_locked(self._clock(), incoming_bytes=0)
        if error is not None:
            self._notify_error(error)
        return error

    def discard_partial(self) -> None:
        """Clear pending text, for example when its websocket disconnects."""
        with self._lock:
            self._dropped_bytes += self._buffered_bytes
            self._clear_partial_locked()

    def _expire_if_needed_locked(
        self, now: float, *, incoming_bytes: int
    ) -> Optional[SignalRFrameError]:
        if self._partial_started_at is None:
            return None

        age = max(0.0, now - self._partial_started_at)
        if age < self._partial_timeout_seconds:
            return None

        error = SignalRFrameError(
            kind=SignalRFrameErrorKind.PARTIAL_TIMEOUT,
            occurred_at=now,
            buffered_bytes=self._buffered_bytes,
            incoming_bytes=incoming_bytes,
            partial_age_seconds=age,
        )
        self._partial_timeouts += 1
        self._dropped_bytes += self._buffered_bytes
        self._clear_partial_locked()
        self._record_error_locked(error)
        return error

    def _clear_partial_locked(self) -> None:
        self._buffer = ""
        self._buffered_bytes = 0
        self._partial_started_at = None

    def _record_error_locked(self, error: SignalRFrameError) -> None:
        self._last_error = error

    def _notify_error(self, error: SignalRFrameError) -> None:
        if self._on_error is not None:
            self._on_error(error)
