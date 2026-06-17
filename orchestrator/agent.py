"""
Orchestrator Agent — coordinates the Arbiter adjudication workflow.

Uses a custom SimpleAdapter so it can explicitly post messages to the Band
room. LangGraphAdapter silently produces no room message for tool-free agents
(no send_message call) — same bug the Defender PR fixed.

Current workflow (Triage / Prosecutor / Judge not yet deployed):
  1. Receive an alert JSON in the room.
  2. Acknowledge receipt with a case-open banner.
  3. Discover the Defender from room participants and forward the alert.
  4. Hold the Defender's position for the Judge (coming soon).
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)

_ALERT_KEYS = ('"alert_id"', '"rule_name"', '"raw_payload"')

SYSTEM_PROMPT = """\
You are the Arbiter Orchestrator for a Security Operations Center adjudication system.

You coordinate the workflow — you do not perform analysis or issue verdicts.

Agents in this system:
- Triage (not yet deployed): enriches alerts, builds the EvidenceBundle with stable evidence_ids.
- Prosecutor (not yet deployed): argues the alert is a real incident.
- Defender (deployed): argues the alert is a false positive. Handle ends with /arbiter-defender.
- Judge (not yet deployed): validates citations, scores severity, issues the Disposition.

Current interim workflow:
1. When an alert JSON arrives, acknowledge it and open the case.
2. Forward the alert to the Defender by mentioning them.
3. Collect the Defender's position and hold it for the Judge.

Rules:
- Never issue a verdict yourself.
- Never allow a destructive action without a Judge verdict and human sign-off.
- Keep the room status clear: announce each stage transition.
"""

WELCOME = (
    "**Orchestrator — Arbiter** ⚖️\n"
    "I coordinate the security alert adjudication pipeline.\n\n"
    "**Stages:**\n"
    "1. 📥 Receive alert → open case\n"
    "2. 🔍 Triage: enrich + build EvidenceBundle *(pending)*\n"
    "3. ⚔️  Prosecutor + 🛡️ Defender: argue both sides in parallel "
    "*(Defender ready, Prosecutor pending)*\n"
    "4. ⚖️  Judge: validate citations, score severity, issue verdict *(pending)*\n\n"
    "Paste an alert JSON to begin."
)


def _clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


class OrchestratorAdapter(SimpleAdapter):
    """Coordinate the adjudication workflow and post all messages explicitly."""

    def __init__(self, llm, self_id: str):
        super().__init__(history_converter=LangChainHistoryConverter())
        self.llm = llm
        self.self_id = self_id

    async def _participants(self, tools) -> list:
        parts = tools.get_participants()
        if inspect.isawaitable(parts):
            parts = await parts
        return parts or []

    async def _others(self, tools) -> list[str]:
        handles = []
        for p in await self._participants(tools):
            handle = _field(p, "handle") or _field(p, "name")
            is_self = (
                _field(p, "id") == self.self_id
                or (handle or "").endswith("/arbiter-orchestrator")
            )
            if handle and not is_self:
                handles.append(handle)
        return handles

    async def _find_agent(self, tools, handle_suffix: str) -> str | None:
        for p in await self._participants(tools):
            handle = _field(p, "handle") or _field(p, "name")
            if handle and handle.endswith(handle_suffix):
                return handle
        return None

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
        logger.info("[ORCHESTRATOR] handling %s in %s", msg.id, room_id)
        user_text = msg.format_for_llm()
        messages = [("system", SYSTEM_PROMPT), *(history or []), ("user", user_text)]

        try:
            mentions = await self._others(tools)

            if is_session_bootstrap:
                await tools.send_message(content=WELCOME, mentions=mentions or None)

            response = await self.llm.ainvoke(messages)
            content = _clean(getattr(response, "content", str(response)))
            if not content:
                content = "Acknowledged. Routing alert through the adjudication pipeline."

            await tools.send_message(content=content, mentions=mentions or None)

            # If the message contains an alert payload, route it to the Defender.
            if any(k in user_text for k in _ALERT_KEYS):
                defender = await self._find_agent(tools, "/arbiter-defender")
                if defender:
                    await tools.send_message(
                        content=(
                            "**[ORCHESTRATOR → DEFENDER]** Alert received. "
                            "Please review and provide your position.\n\n" + user_text
                        ),
                        mentions=[defender],
                    )
                    logger.info("[ORCHESTRATOR] forwarded alert to %s", defender)
                else:
                    await tools.send_message(
                        content=(
                            "⚠️ Defender not found in room. "
                            "Add the Defender agent as a participant and resend the alert."
                        ),
                        mentions=mentions or None,
                    )

        except Exception:
            logger.exception("[ORCHESTRATOR] failed on %s", msg.id)
            try:
                await tools.send_message(
                    content="Internal error in Orchestrator; see agent logs.",
                    mentions=(await self._others(tools)) or None,
                )
            except Exception:
                logger.exception("[ORCHESTRATOR] error-reply also failed on %s", msg.id)


async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("my_agent")

    llm = ChatOpenAI(
        model="Qwen/Qwen3-32B",
        base_url="https://api.featherless.ai/v1",
        api_key=os.getenv("FEATHERLESS_API_KEY"),
        temperature=0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    agent = Agent.create(
        adapter=OrchestratorAdapter(llm, self_id=agent_id),
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
