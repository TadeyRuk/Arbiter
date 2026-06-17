"""
Prosecutor Agent - LangChain + Featherless AI
Argues the alert is a true positive, grounded in evidence.
"""
import asyncio
import inspect
import logging
import os
import re

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from band import Agent
from band.config import load_agent_config
from band.core.simple_adapter import SimpleAdapter
from band.converters.langchain import LangChainHistoryConverter

from prosecution import ROOM_PROMPT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("prosecutor")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


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
                or (handle or "").endswith("/arbiter-prosecutor")
            )
            if handle and not is_self:
                handles.append(handle)
        return handles

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
        user_text = msg.format_for_llm()
        messages = [("system", ROOM_PROMPT), *(history or []), ("user", user_text)]
        try:
            mentions = await self._others(tools)
            if is_session_bootstrap:
                await tools.send_message(content=WELCOME, mentions=mentions or None)
            response = await self.llm.ainvoke(messages)
            content = _clean(getattr(response, "content", str(response)))
            if not content:
                content = "I couldn't form a grounded position on this alert."
            await tools.send_message(content=content, mentions=mentions or None)
            logger.info(
                "[PROSECUTOR] replied %d chars to %s (mentions=%s)",
                len(content), room_id, mentions,
            )
        except Exception:
            logger.exception("[PROSECUTOR] failed on %s", msg.id)
            try:
                await tools.send_message(
                    content="Internal error while arguing this alert; see agent logs.",
                    mentions=(await self._others(tools)) or None,
                )
            except Exception:
                logger.exception("[PROSECUTOR] error-reply also failed on %s", msg.id)


async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("prosecutor_agent")

    while True:
        llm = ChatOpenAI(
            model="Qwen/Qwen3-32B",
            base_url="https://api.featherless.ai/v1",
            api_key=os.getenv("FEATHERLESS_API_KEY"),
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
