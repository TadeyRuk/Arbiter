"""
Bridge terminal WARNING+ logs and uncaught exceptions into the Band chat room
via the System Diagnostics Agent.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any

DIAGNOSTICS_PREFIX = "[SYSTEM_DIAGNOSTICS]"
AGENT_ERROR_PREFIX = "[AGENT_ERROR]"
MAX_MESSAGE_CHARS = 3500
DEBOUNCE_SECONDS = 30
RING_BUFFER_SIZE = 50

_ARBITER_LOGGER_PREFIXES = (
    "orchestrator",
    "defender",
    "prosecutor",
    "judge",
    "triage",
    "run_all",
    "diagnostics",
    "__main__",
)


@dataclass
class DiagnosticEvent:
    level: str
    logger_name: str
    message: str
    timestamp: str
    traceback_text: str = ""


@dataclass
class DiagnosticsBridge:
    """Process-local queue between logging and the Diagnostics Band agent."""

    _queue: Queue[DiagnosticEvent] = field(default_factory=Queue)
    _buffer: deque[DiagnosticEvent] = field(
        default_factory=lambda: deque(maxlen=RING_BUFFER_SIZE)
    )
    _tools: Any = None
    _debounce: dict[tuple[str, str], float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def enqueue(self, event: DiagnosticEvent) -> None:
        key = (event.logger_name, event.message)
        now = time.monotonic()
        with self._lock:
            last = self._debounce.get(key)
            if last is not None and (now - last) < DEBOUNCE_SECONDS:
                return
            self._debounce[key] = now
            self._buffer.append(event)
        self._queue.put(event)

    def set_tools(self, tools: Any) -> None:
        self._tools = tools

    def get_recent(self, limit: int = 10) -> list[DiagnosticEvent]:
        with self._lock:
            return list(self._buffer)[-limit:]

    def drain_nowait(self) -> DiagnosticEvent | None:
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

    async def drain_loop(self, stop_event: Any | None = None) -> None:
        """Background task: post queued events to Band."""
        while stop_event is None or not stop_event.is_set():
            event = self.drain_nowait()
            if event is None:
                await _async_sleep(0.5)
                continue
            if self._tools is None:
                await _async_sleep(0.5)
                continue
            await post_diagnostic(self._tools, event)


bridge = DiagnosticsBridge()
_installed = False


def _async_sleep(seconds: float) -> Any:
    import asyncio

    return asyncio.sleep(seconds)


def _is_arbiter_logger(name: str) -> bool:
    if not name:
        return False
    return any(name == p or name.startswith(p + ".") for p in _ARBITER_LOGGER_PREFIXES)


def format_diagnostic_message(event: DiagnosticEvent) -> str:
    """Format a diagnostic event for Band chat (markdown, truncated)."""
    lines = [
        f"**{DIAGNOSTICS_PREFIX} System Diagnostics Agent**",
        f"**Level:** {event.level}",
        f"**Logger:** `{event.logger_name}`",
        f"**Time:** {event.timestamp}",
        "",
        event.message,
    ]
    if event.traceback_text:
        lines.extend(["", "```", event.traceback_text.rstrip(), "```"])
    text = "\n".join(lines)
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 20] + "\n\n… _(truncated)_"
    return text


def format_agent_error(agent_name: str, exc: BaseException) -> str:
    return f"{AGENT_ERROR_PREFIX} {agent_name}: {type(exc).__name__}: {exc}"


def _record_from_log(record: logging.LogRecord) -> DiagnosticEvent:
    tb = ""
    if record.exc_info and record.exc_info[0] is not None:
        tb = "".join(traceback.format_exception(*record.exc_info))
    elif record.levelno >= logging.ERROR and record.stack_info:
        tb = record.stack_info

    ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    return DiagnosticEvent(
        level=record.levelname,
        logger_name=record.name,
        message=record.getMessage(),
        timestamp=ts,
        traceback_text=tb,
    )


class BandDiagnosticsHandler(logging.Handler):
    """Non-blocking handler: enqueue WARNING+ from Arbiter loggers only."""

    def __init__(self, level: int = logging.WARNING) -> None:
        super().__init__(level=level)

    def emit(self, record: logging.LogRecord) -> None:
        if not _is_arbiter_logger(record.name):
            return
        try:
            bridge.enqueue(_record_from_log(record))
        except Exception:
            self.handleError(record)


def _excepthook(exc_type, exc_value, exc_tb) -> None:
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    event = DiagnosticEvent(
        level="CRITICAL",
        logger_name="uncaught",
        message=f"Uncaught exception: {exc_type.__name__}: {exc_value}",
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        traceback_text=tb_text,
    )
    bridge.enqueue(event)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_diagnostics_logging() -> None:
    """Idempotent: attach handler and excepthook."""
    global _installed
    if _installed:
        return
    handler = BandDiagnosticsHandler(level=logging.WARNING)
    logging.getLogger().addHandler(handler)
    sys.excepthook = _excepthook
    _installed = True


def _field(p: Any, key: str) -> Any:
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


async def _human_mentions(tools: Any) -> list[str]:
    parts = await tools.get_participants()
    mentions: list[str] = []
    for p in parts or []:
        if _field(p, "type") == "human" or _field(p, "is_human"):
            handle = _field(p, "handle") or _field(p, "name")
            if handle:
                mentions.append(handle)
    if not mentions:
        for p in parts or []:
            handle = _field(p, "handle") or _field(p, "name")
            if handle:
                mentions.append(handle)
                break
    return mentions


async def post_diagnostic(tools: Any, event: DiagnosticEvent) -> None:
    """Post one diagnostic event to Band; fall back to send_event if needed."""
    content = format_diagnostic_message(event)
    mentions = await _human_mentions(tools)
    try:
        await tools.send_message(content=content, mentions=mentions or None)
    except Exception:
        logging.getLogger("diagnostics").exception(
            "send_message failed; falling back to send_event"
        )
        await tools.send_event(
            content=content,
            message_type="task",
            metadata={"arbiter_message_type": "system_diagnostics"},
        )
