"""Offline tests for shared/diagnostics.py."""
import logging

from shared.diagnostics import (
    BandDiagnosticsHandler,
    DiagnosticEvent,
    DiagnosticsBridge,
    _record_from_log,
    format_diagnostic_message,
    install_diagnostics_logging,
)


def test_format_diagnostic_message_includes_level_logger_traceback():
    event = DiagnosticEvent(
        level="ERROR",
        logger_name="defender",
        message="LLM call failed",
        timestamp="2026-06-18 12:00:00 UTC",
        traceback_text="Traceback (most recent call last):\n  File ...\nValueError: boom",
    )
    text = format_diagnostic_message(event)
    assert "System Diagnostics Agent" in text
    assert "ERROR" in text
    assert "`defender`" in text
    assert "LLM call failed" in text
    assert "ValueError: boom" in text


def test_handler_enqueues_warning_ignores_info():
    test_bridge = DiagnosticsBridge()

    class TestHandler(BandDiagnosticsHandler):
        def emit(self, record):
            from shared.diagnostics import _is_arbiter_logger

            if not _is_arbiter_logger(record.name):
                return
            if record.levelno < logging.WARNING:
                return
            test_bridge.enqueue(_record_from_log(record))

    handler = TestHandler(level=logging.WARNING)
    handler.emit(
        logging.LogRecord(
            name="orchestrator",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="routine info",
            args=(),
            exc_info=None,
        )
    )
    assert test_bridge.drain_nowait() is None

    handler.emit(
        logging.LogRecord(
            name="orchestrator",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="missing agent",
            args=(),
            exc_info=None,
        )
    )
    event = test_bridge.drain_nowait()
    assert event is not None
    assert event.level == "WARNING"
    assert event.message == "missing agent"


def test_debounce_suppresses_duplicates():
    test_bridge = DiagnosticsBridge()
    event = DiagnosticEvent(
        level="WARNING",
        logger_name="prosecutor",
        message="websocket ended; reconnecting",
        timestamp="2026-06-18 12:00:00 UTC",
    )
    test_bridge.enqueue(event)
    test_bridge.enqueue(event)
    assert test_bridge.drain_nowait() is not None
    assert test_bridge.drain_nowait() is None


def test_ring_buffer_returns_recent():
    test_bridge = DiagnosticsBridge()
    for i in range(5):
        test_bridge.enqueue(
            DiagnosticEvent(
                level="WARNING",
                logger_name="test",
                message=f"msg-{i}",
                timestamp="t",
            )
        )
    recent = test_bridge.get_recent(3)
    assert len(recent) == 3
    assert recent[-1].message == "msg-4"


def test_install_diagnostics_logging_is_idempotent():
    install_diagnostics_logging()
    root_handlers = logging.getLogger().handlers
    count_before = sum(1 for h in root_handlers if isinstance(h, BandDiagnosticsHandler))
    install_diagnostics_logging()
    count_after = sum(1 for h in root_handlers if isinstance(h, BandDiagnosticsHandler))
    assert count_before == count_after
    assert count_after >= 1
