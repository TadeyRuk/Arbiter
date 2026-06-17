"""
Judge Agent — LangChain + Featherless AI
Validates citations, scores severity, issues verdict, gates human escalation.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

logging.basicConfig(level=logging.INFO)

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

async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("judge_agent")

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
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
