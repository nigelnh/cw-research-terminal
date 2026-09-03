from dataclasses import fields
import threading

from app.market_data.providers.signalr_text_frame_adapter import (
    SIGNALR_RECORD_SEPARATOR,
    SignalRFrameErrorKind,
    SignalRTextFrameAdapter,
)


class ManualClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_partial_frame_is_buffered_then_forwarded_unchanged() -> None:
    calls = []
    adapter = SignalRTextFrameAdapter(lambda app, raw: calls.append((app, raw)))
    app = object()

    first = adapter.on_message(app, '{"type":1,"target":"tick",')
    second = adapter.on_message(app, '"arguments":[1]}\x1e')

    assert first.emitted_frames == 0
    assert second.emitted_frames == 1
    assert calls == [
        (app, '{"type":1,"target":"tick","arguments":[1]}\x1e')
    ]
    assert adapter.stats.buffered_bytes == 0


def test_multiple_frames_and_handshake_are_preserved_as_one_batch() -> None:
    calls = []
    adapter = SignalRTextFrameAdapter(lambda app, raw: calls.append(raw))
    batch = (
        "{}"
        + SIGNALR_RECORD_SEPARATOR
        + '{"type":1,"target":"tick","arguments":[]}'
        + SIGNALR_RECORD_SEPARATOR
    )

    result = adapter.feed(object(), batch)

    assert calls == [batch]
    assert result.emitted_batches == 1
    assert result.emitted_frames == 2
    assert adapter.stats.emitted_batches == 1
    assert adapter.stats.emitted_frames == 2


def test_partial_timeout_drops_payload_and_reports_typed_metadata() -> None:
    clock = ManualClock()
    calls = []
    errors = []
    adapter = SignalRTextFrameAdapter(
        lambda app, raw: calls.append(raw),
        on_error=errors.append,
        clock=clock,
        partial_timeout_seconds=5.0,
    )

    adapter.feed(None, '{"secret":"must-not-escape"')
    clock.advance(5.0)
    result = adapter.feed(None, "}\x1e")

    assert calls == []
    assert result.error is not None
    assert result.error.kind is SignalRFrameErrorKind.PARTIAL_TIMEOUT
    assert result.error.partial_age_seconds == 5.0
    assert result.error.buffered_bytes == len('{"secret":"must-not-escape"')
    assert errors == [result.error]
    assert adapter.stats.partial_timeouts == 1
    assert adapter.stats.buffered_bytes == 0
    assert "must-not-escape" not in repr(result.error)
    assert all(field.name not in {"payload", "raw", "message"} for field in fields(result.error))


def test_oversized_partial_is_dropped_and_adapter_can_recover() -> None:
    calls = []
    errors = []
    adapter = SignalRTextFrameAdapter(
        lambda app, raw: calls.append(raw),
        on_error=errors.append,
        max_buffer_bytes=8,
    )

    result = adapter.feed(None, "123456789")

    assert result.error is not None
    assert result.error.kind is SignalRFrameErrorKind.BUFFER_OVERFLOW
    assert result.error.limit_bytes == 8
    assert result.error.buffered_bytes == 0
    assert adapter.stats.buffer_overflows == 1
    assert adapter.stats.buffered_bytes == 0
    assert adapter.stats.dropped_bytes == 9
    assert errors == [result.error]

    recovered = adapter.feed(None, "{}\x1e")
    assert recovered.emitted_frames == 1
    assert calls == ["{}\x1e"]


def test_callback_parse_failure_reports_payload_free_frame_error() -> None:
    errors = []

    def reject_frame(app, raw) -> None:
        raise ValueError("parser included sensitive frame text")

    adapter = SignalRTextFrameAdapter(reject_frame, on_error=errors.append)

    result = adapter.feed(None, '{"secret":true}\x1e')

    assert result.error is not None
    assert result.error.kind is SignalRFrameErrorKind.FRAME_ERROR
    assert result.error.exception_type == "ValueError"
    assert adapter.stats.frame_errors == 1
    assert adapter.stats.emitted_frames == 0
    assert errors == [result.error]
    assert "sensitive" not in repr(result.error)


def test_message_callback_runs_outside_state_lock() -> None:
    """A signalrcore callback may synchronously trigger teardown on another thread."""

    teardown_finished = threading.Event()
    callback_finished = threading.Event()
    adapter: SignalRTextFrameAdapter

    def callback(app, raw) -> None:
        worker = threading.Thread(
            target=lambda: (adapter.discard_partial(), teardown_finished.set())
        )
        worker.start()
        worker.join(timeout=1.0)
        if teardown_finished.is_set():
            callback_finished.set()

    adapter = SignalRTextFrameAdapter(callback)

    result = adapter.feed(None, "{}\x1e")

    assert result.emitted_frames == 1
    assert teardown_finished.is_set()
    assert callback_finished.is_set()


def test_timeout_callback_runs_outside_state_lock() -> None:
    clock = ManualClock()
    callback_finished = threading.Event()
    adapter: SignalRTextFrameAdapter

    def on_error(error) -> None:
        worker = threading.Thread(target=lambda: (adapter.stats, callback_finished.set()))
        worker.start()
        worker.join(timeout=1.0)

    adapter = SignalRTextFrameAdapter(
        lambda app, raw: None,
        on_error=on_error,
        clock=clock,
        partial_timeout_seconds=5.0,
    )
    adapter.feed(None, '{"partial":true')
    clock.advance(5.0)

    error = adapter.expire_partial()

    assert error is not None
    assert error.kind is SignalRFrameErrorKind.PARTIAL_TIMEOUT
    assert callback_finished.is_set()


def test_concurrent_timeout_checks_expire_a_partial_only_once() -> None:
    clock = ManualClock()
    adapter = SignalRTextFrameAdapter(
        lambda app, raw: None,
        clock=clock,
        partial_timeout_seconds=5.0,
    )
    partial = '{"partial":true'
    adapter.feed(None, partial)
    clock.advance(5.0)
    start = threading.Barrier(9)
    errors = []

    def expire() -> None:
        start.wait()
        errors.append(adapter.expire_partial())

    workers = [threading.Thread(target=expire) for _ in range(8)]
    for worker in workers:
        worker.start()
    start.wait()
    for worker in workers:
        worker.join(timeout=1.0)

    assert sum(error is not None for error in errors) == 1
    assert adapter.stats.partial_timeouts == 1
    assert adapter.stats.dropped_bytes == len(partial.encode("utf-8"))
    assert adapter.stats.buffered_bytes == 0
