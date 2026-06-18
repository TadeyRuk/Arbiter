"""
Judge Agent — LangChain + Featherless AI
Validates citations, scores severity, issues verdict, gates human escalation.
"""
import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("judge")
JUDGE_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = JUDGE_DIR / "agent_config.yaml"
ORCHESTRATOR_HANDLE_SUFFIX = "/arbiter-orchestrator2"
JUDGE_HANDOFF_MARKERS = (
    "[ORCHESTRATOR → JUDGE]",
    "[ORCHESTRATOR -> JUDGE]",
)

SYSTEM_PROMPT = """\
You are the Judge Agent for the Arbiter security adjudication system.

Responsibilities:
1. CITATION VALIDATION: Strike any claim citing an evidence_id not in the EvidenceBundle.
   A struck claim cannot be used in the verdict.
2. EVIDENCE REQUEST: If a decisive question is unanswered, send the case back to Triage
   ONCE. If still unanswered after re-enrichment, proceed with available evidence.
3. SEVERITY SCORING: Score against the rubric (0-10 each):
   - evidence_strength (30%)
   - asset_criticality (25%)
   - mitre_severity (20%)
   - blast_radius (15%)
   - base_rate (10%)
4. VERDICT: Issue one of: real_incident | false_positive | escalate_human | needs_more_evidence
5. ESCALATION: If verdict is real_incident with score >= 7, OR action is disruptive
   (isolate host, disable credential, block production IP), set requires_human_approval=true.
   Nothing destructive executes without human sign-off.
6. OUTPUT: Produce a Disposition JSON with your verdict, confidence (0.0-1.0),
   severity, score breakdown, and reasoning.

Be calibrated. An honest low-confidence verdict is better than a false certainty.
"""

import inspect
from band.preprocessing import DefaultPreprocessor

# helper function _field
def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


def _is_targeted_to_judge(content: str, self_handle: str | None, sender_handle: str | None) -> bool:
    if self_handle and self_handle.lower() in content.lower():
        return True
    if sender_handle and sender_handle.lower().endswith(ORCHESTRATOR_HANDLE_SUFFIX):
        return any(marker in content for marker in JUDGE_HANDOFF_MARKERS)
    return False


class JudgePreprocessor(DefaultPreprocessor):
    """Only pass messages to LangGraph if Judge is explicitly spoken to/mentioned."""

    async def process(self, ctx: inspect.Any, event: inspect.Any, agent_id: str) -> inspect.Any:
        agent_input = await super().process(ctx=ctx, event=event, agent_id=agent_id)
        if agent_input is None:
            return None

        # 0. Ignore messages sent by self
        if agent_input.msg.sender_id == agent_id:
            return None

        tools = agent_input.tools
        parts = tools.get_participants()
        if inspect.isawaitable(parts):
            parts = await parts
        
        self_handle = None
        for p in parts or []:
            if _field(p, "id") == agent_id:
                self_handle = _field(p, "handle") or _field(p, "name")
                break

        # Ignore messages from other non-coordinating agents (Prosecutor, Defender, Triage)
        sender_handle = None
        for p in parts or []:
            if _field(p, "id") == agent_input.msg.sender_id:
                sender_handle = _field(p, "handle") or _field(p, "name")
                break

        if sender_handle:
            sh_lower = sender_handle.lower()
            if sh_lower.endswith("/prosecuter") or sh_lower.endswith("/defender") or sh_lower.endswith("/triage"):
                return None
                
        if not _is_targeted_to_judge(getattr(agent_input.msg, "content", None) or agent_input.msg.format_for_llm(), self_handle, sender_handle):
            return None

        return agent_input


async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("judge_agent", config_path=AGENT_CONFIG_PATH)

    model = (
        os.getenv("FEATHERLESS_MODEL_JUDGE")
        or os.getenv("FEATHERLESS_MODEL")
        or "Qwen/Qwen3-32B"
    )
    llm = ChatOpenAI(
        model=model,
        base_url="https://api.featherless.ai/v1",
        api_key=os.getenv("FEATHERLESS_API_KEY_JUDGE") or os.getenv("FEATHERLESS_API_KEY"),
    )

    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section=SYSTEM_PROMPT,
    )

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
        preprocessor=JudgePreprocessor(),
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
