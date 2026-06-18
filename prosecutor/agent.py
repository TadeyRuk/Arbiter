"""
Prosecutor Agent - LangChain + Featherless AI
Argues the alert is a true positive, grounded in evidence.
"""
import asyncio
import inspect
import logging
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from band import Agent
from band.config import load_agent_config
from band.core.simple_adapter import SimpleAdapter
from band.converters.langchain import LangChainHistoryConverter

try:
    from .prosecution import ROOM_PROMPT
except ImportError:
    from prosecution import ROOM_PROMPT

try:
    from shared.diagnostics import format_agent_error
except ImportError:
    def format_agent_error(agent_name: str, exc: BaseException) -> str:
        return f"[AGENT_ERROR] {agent_name}: {type(exc).__name__}: {exc}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prosecutor")
PROSECUTOR_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = PROSECUTOR_DIR / "agent_config.yaml"
ORCHESTRATOR_HANDLE_SUFFIX = "/arbiter-orchestrator2"
PROSECUTOR_HANDOFF_MARKERS = (
    "[ORCHESTRATOR → PROSECUTOR]",
    "[ORCHESTRATOR -> PROSECUTOR]",
)

_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def _extract_think(text: str) -> str | None:
    m = _THINK.search(text or "")
    return m.group(1).strip() if m else None


def _log_think(agent: str, think: str) -> None:
    sep = "─" * 60
    lines = "\n".join(f"  {line}" for line in think.splitlines())
    logger.info("\n%s\n  🧠  %s THINKING\n%s\n%s\n%s", sep, agent, sep, lines, sep)


def _clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


def _is_targeted_to_prosecutor(content: str, self_handle: str | None, sender_handle: str | None) -> bool:
    if self_handle and self_handle.lower() in content.lower():
        return True
    if sender_handle and sender_handle.lower().endswith(ORCHESTRATOR_HANDLE_SUFFIX):
        return any(marker in content for marker in PROSECUTOR_HANDOFF_MARKERS)
    return False


WELCOME = (
    "**Prosecutor Agent — Arbiter** ⚖️\n"
    "I argue the *true-positive (malicious)* side of security alerts, grounded "
    "only in the evidence you provide.\n\n"
    "**What I can do:**\n"
    "- Take an alert + EvidenceBundle and return a cited verdict — "
    "`REAL INCIDENT`, `CONCEDE`, or `NEED MORE EVIDENCE`\n"
    "- Map behaviors to MITRE ATT&CK techniques where applicable\n"
    "- Back every claim with the `evidence_id` it rests on (e.g. EVD-2)\n"
    "- Concede points the evidence decisively defeats — no overreach\n\n"
    "Paste an alert with its EvidenceBundle (items carrying `evidence_id`s) "
    "and I'll give you a cited position."
)


class ProsecutorAdapter(SimpleAdapter):
    """Prompt the LLM with room history, post the answer explicitly."""

    def __init__(self, llm, self_id: str):
        super().__init__(history_converter=LangChainHistoryConverter())
        self.llm = llm
        self.self_id = self_id

    async def _others(self, tools) -> list[str]:
        parts = tools.get_participants()
        if inspect.isawaitable(parts):
            parts = await parts
        handles = []
        for p in parts or []:
            handle = _field(p, "handle") or _field(p, "name")
            is_self = (
                _field(p, "id") == self.self_id
                or (handle or "").endswith("/prosecuter")
            )
            if handle and not is_self:
                handles.append(handle)
        return handles

    async def _participants(self, tools) -> list:
        parts = tools.get_participants()
        if inspect.isawaitable(parts):
            parts = await parts
        return parts or []

    def _is_agent_handle(self, handle: str | None) -> bool:
        return bool(
            handle
            and handle.endswith(
                (
                    "/arbiter-orchestrator2",
                    "/triage",
                    "/prosecuter",
                    "/defender",
                    "/judge",
                )
            )
        )

    async def _reply_mentions(self, tools, sender_id: str | None = None) -> list[str]:
        parts = await self._participants(tools)
        if sender_id and sender_id != self.self_id:
            for p in parts:
                if _field(p, "id") == sender_id:
                    handle = _field(p, "handle") or _field(p, "name")
                    if handle:
                        return [handle]

        for p in parts:
            handle = _field(p, "handle") or _field(p, "name")
            if handle and not self._is_agent_handle(handle):
                return [handle]
        return []

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
        logger.info("[PROSECUTOR] handling %s in %s", msg.id, room_id)
        
        # 0. Ignore messages sent by self
        if msg.sender_id == self.self_id:
            logger.info("[PROSECUTOR] ignoring message %s (sent by self)", msg.id)
            return

        # 1. Greeting once on bootstrap, then exit immediately to prevent runaway loop at start
        if is_session_bootstrap:
            mentions = await self._reply_mentions(tools, msg.sender_id)
            await tools.send_message(content=WELCOME, mentions=mentions or None)
            return

        # Check if sender is another agent we shouldn't listen to directly (Triage, Defender, Judge)
        parts = await self._participants(tools)
        
        sender_handle = None
        for p in parts or []:
            if _field(p, "id") == msg.sender_id:
                sender_handle = _field(p, "handle") or _field(p, "name")
                break

        if sender_handle:
            sh_lower = sender_handle.lower()
            if sh_lower.endswith("/defender") or sh_lower.endswith("/triage") or sh_lower.endswith("/judge"):
                logger.info("[PROSECUTOR] ignoring message %s (sent by other agent %s)", msg.id, sender_handle)
                return

        # 2. Check if spoken to
        self_handle = None
        for p in parts or []:
            if _field(p, "id") == self.self_id:
                self_handle = _field(p, "handle") or _field(p, "name")
                break
                
        if not _is_targeted_to_prosecutor(getattr(msg, "content", None) or msg.format_for_llm(), self_handle, sender_handle):
            logger.info("[PROSECUTOR] ignoring message %s (not spoken to)", msg.id)
            return

        user_text = msg.format_for_llm()
        mentions = await self._reply_mentions(tools, msg.sender_id)
        messages = [("system", ROOM_PROMPT), *(history or []), ("user", user_text)]
        try:
            response = await self.llm.ainvoke(messages)
            raw = getattr(response, "content", str(response))
            think = _extract_think(raw)
            if think:
                _log_think("PROSECUTOR", think)
            content = _clean(raw) or "I couldn't form a grounded position on this alert."
            await tools.send_message(content=content, mentions=mentions or None)
            logger.info(
                "[PROSECUTOR] replied %d chars to %s (mentions=%s)",
                len(content), room_id, mentions,
            )
        except Exception as exc:
            logger.exception("[PROSECUTOR] failed on %s", msg.id)
            try:
                await tools.send_message(
                    content=format_agent_error("prosecutor", exc),
                    mentions=(await self._reply_mentions(tools, msg.sender_id)) or None,
                )
            except Exception:
                logger.exception("[PROSECUTOR] error-reply also failed on %s", msg.id)


async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("prosecutor_agent", config_path=AGENT_CONFIG_PATH)

    while True:
        model = (
            os.getenv("FEATHERLESS_MODEL_PROSECUTOR")
            or os.getenv("FEATHERLESS_MODEL")
            or "Qwen/Qwen3-32B"
        )
        llm = ChatOpenAI(
            model=model,
            base_url="https://api.featherless.ai/v1",
            api_key=os.getenv("FEATHERLESS_API_KEY_PROSECUTOR") or os.getenv("FEATHERLESS_API_KEY"),
            temperature=0.2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

        agent = Agent.create(
            adapter=ProsecutorAdapter(llm, self_id=agent_id),
            agent_id=agent_id,
            api_key=api_key,
            ws_url=os.getenv("THENVOI_WS_URL"),
            rest_url=os.getenv("THENVOI_REST_URL"),
        )

        try:
            await agent.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[PROSECUTOR] websocket run failed; reconnecting")
        else:
            logger.warning("[PROSECUTOR] websocket ended; reconnecting")

        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
