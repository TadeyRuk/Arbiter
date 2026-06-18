"""
System Diagnostics Agent — mirrors WARNING+ terminal logs into the Band chat room.

No LLM required; only Band credentials (agent_config.yaml).
"""
import asyncio
import logging
import os
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

    async def _start_drain(self, tools) -> None:
        bridge.set_tools(tools)
        if self._drain_task is None or self._drain_task.done():
            self._stop.clear()
            self._drain_task = asyncio.create_task(bridge.drain_loop(self._stop))
            logger.info("[DIAGNOSTICS] drain loop started")

    async def on_message(self, msg, tools, history=None, is_session_bootstrap=False):
        if is_session_bootstrap:
            await self._start_drain(tools)
            mentions = await self._human_mentions(tools)
            await tools.send_message(content=WELCOME, mentions=mentions or None)
            logger.info("[DIAGNOSTICS] welcome posted")
            return

        if msg.sender_id == self.self_id:
            return

        await self._start_drain(tools)

        text = (getattr(msg, "content", None) or msg.format_for_llm() or "").strip().lower()
        if text in ("recent", "status", "diagnostics", "logs"):
            recent = bridge.get_recent(10)
            if not recent:
                body = f"{DIAGNOSTICS_PREFIX} No buffered diagnostics yet."
            else:
                parts = [format_diagnostic_message(e) for e in recent]
                body = f"{DIAGNOSTICS_PREFIX} **Recent diagnostics ({len(recent)}):**\n\n" + (
                    "\n\n---\n\n".join(parts)
                )
            mentions = await self._human_mentions(tools)
            await tools.send_message(content=body, mentions=mentions or None)
            return

        mentions = await self._human_mentions(tools)
        await tools.send_message(
            content=(
                f"{DIAGNOSTICS_PREFIX} Monitoring active. "
                "Say `recent` or `status` for buffered log entries."
            ),
            mentions=mentions or None,
        )


async def main():
    load_dotenv()
    install_diagnostics_logging()

    agent_id, api_key = load_agent_config(
        "diagnostics_agent", config_path=AGENT_CONFIG_PATH
    )

    agent = Agent.create(
        adapter=DiagnosticsAdapter(self_id=agent_id),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
    )

    logger.info("System Diagnostics Agent starting (agent_id=%s)", agent_id)
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
