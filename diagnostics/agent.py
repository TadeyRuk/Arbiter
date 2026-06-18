"""
System Diagnostics Agent — mirrors WARNING+ terminal logs into the Band chat room.

No LLM required; only Band credentials (agent_config.yaml).
"""
import asyncio
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from band import Agent
from band.config import load_agent_config
from band.core.simple_adapter import SimpleAdapter

try:
    from shared.diagnostics import (
        DIAGNOSTICS_PREFIX,
        DiagnosticEvent,
        bridge,
        format_diagnostic_message,
        install_diagnostics_logging,
        post_diagnostic,
    )
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from shared.diagnostics import (
        DIAGNOSTICS_PREFIX,
        DiagnosticEvent,
        bridge,
        format_diagnostic_message,
        install_diagnostics_logging,
        post_diagnostic,
    )

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diagnostics")
DIAGNOSTICS_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = DIAGNOSTICS_DIR / "agent_config.yaml"

WELCOME = (
    "**System Diagnostics Agent** 🔧\n"
    "I forward WARNING-and-above terminal output from Arbiter agents into this "
    "chat room so failures are visible when Band does not surface them.\n\n"
    "**What I post:**\n"
    "- Agent exceptions and tracebacks\n"
    "- WARNING-level issues (missing agents, reconnect loops, etc.)\n"
    "- Uncaught process crashes\n\n"
    "Mention me with `recent` or `status` to see the last buffered diagnostics."
)


def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


_COMMANDS = ("recent", "status", "diagnostics", "logs")


def _is_diagnostic_command(text: str) -> bool:
    """Match commands even when the message includes @mention handles."""
    lowered = (text or "").strip().lower()
    return any(re.search(rf"\b{cmd}\b", lowered) for cmd in _COMMANDS)


class DiagnosticsAdapter(SimpleAdapter):
    """Passive monitor: drain log queue and post to Band."""

    def __init__(self, self_id: str):
        super().__init__()
        self.self_id = self_id
        self._drain_task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def _human_mentions(self, tools) -> list[str]:
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

    async def _reply_mentions(self, tools, sender_id: str | None = None) -> list[str]:
        """Prefer @mentioning the requester; fall back to any human in the room."""
        if sender_id and sender_id != self.self_id:
            for p in await tools.get_participants() or []:
                if _field(p, "id") == sender_id:
                    handle = _field(p, "handle") or _field(p, "name")
                    if handle:
                        return [handle]
        return await self._human_mentions(tools)

    async def _send(
        self, tools, content: str, sender_id: str | None, room_id: str
    ) -> None:
        mentions = await self._reply_mentions(tools, sender_id)
        try:
            await tools.send_message(content=content, mentions=mentions or None)
        except Exception:
            logger.exception(
                "[DIAGNOSTICS] send_message failed in %s; falling back to send_event",
                room_id,
            )
            await tools.send_event(
                content=content,
                message_type="task",
                metadata={"arbiter_message_type": "system_diagnostics"},
            )

    async def _start_drain(self, tools) -> None:
        bridge.set_tools(tools)
        if self._drain_task is None or self._drain_task.done():
            self._stop.clear()
            self._drain_task = asyncio.create_task(bridge.drain_loop(self._stop))
            logger.info("[DIAGNOSTICS] drain loop started")

    async def on_message(
        self,
        msg,
        tools,
        history,
        participants_msg,
        contacts_msg,
        *,
        is_session_bootstrap: bool,
        room_id: str,
    ) -> None:
        try:
            if is_session_bootstrap:
                await self._start_drain(tools)
                await self._send(tools, WELCOME, msg.sender_id, room_id)
                logger.info("[DIAGNOSTICS] welcome posted in %s", room_id)
                return

            if msg.sender_id == self.self_id:
                return

            await self._start_drain(tools)

            user_text = getattr(msg, "content", None) or msg.format_for_llm()
            if _is_diagnostic_command(user_text):
                recent = bridge.get_recent(10)
                if not recent:
                    body = f"{DIAGNOSTICS_PREFIX} No buffered diagnostics yet."
                else:
                    parts = [format_diagnostic_message(e) for e in recent]
                    body = (
                        f"{DIAGNOSTICS_PREFIX} **Recent diagnostics ({len(recent)}):**\n\n"
                        + "\n\n---\n\n".join(parts)
                    )
                await self._send(tools, body, msg.sender_id, room_id)
                return

            await self._send(
                tools,
                (
                    f"{DIAGNOSTICS_PREFIX} Monitoring active. "
                    "Say `recent` or `status` for buffered log entries."
                ),
                msg.sender_id,
                room_id,
            )
        except Exception:
            logger.exception("[DIAGNOSTICS] failed on %s in %s", msg.id, room_id)
            try:
                await self._send(
                    tools,
                    f"{DIAGNOSTICS_PREFIX} Internal error; see terminal logs.",
                    msg.sender_id,
                    room_id,
                )
            except Exception:
                logger.exception("[DIAGNOSTICS] error-reply also failed on %s", msg.id)


async def main():
    # Band URLs live in the repo-root .env; agent credentials in agent_config.yaml.
    load_dotenv(DIAGNOSTICS_DIR / ".env")
    load_dotenv(DIAGNOSTICS_DIR.parent / ".env", override=False)
    install_diagnostics_logging()

    agent_id, api_key = load_agent_config(
        "diagnostics_agent", config_path=AGENT_CONFIG_PATH
    )

    ws_url = os.getenv("THENVOI_WS_URL")
    rest_url = os.getenv("THENVOI_REST_URL")
    if not ws_url or not rest_url:
        raise RuntimeError(
            "Missing THENVOI_WS_URL or THENVOI_REST_URL. "
            "Copy the Band URLs from the repo-root .env.example into .env "
            "(diagnostics does not use a Featherless API key)."
        )

    agent = Agent.create(
        adapter=DiagnosticsAdapter(self_id=agent_id),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )

    logger.info("System Diagnostics Agent starting (agent_id=%s)", agent_id)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
