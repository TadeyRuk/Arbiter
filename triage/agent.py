"""
Triage Agent — LangChain + Claude Haiku (Anthropic)
Enriches the alert and builds the evidence bundle.
Every fact gets a stable evidence_id. No other agent introduces evidence.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config

logging.basicConfig(level=logging.INFO)

async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("triage_agent")

    llm = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
    )

    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section="""
        You are the Triage Agent for the Arbiter security adjudication system.

        When given a security alert:
        1. Normalize the raw alert payload into a structured format.
        2. Enrich it: pull asset criticality, baseline behavior, CMDB tags, process lineage.
        3. Assign a stable evidence_id to every fact (format: EVD-<number>).
        4. Produce a complete EvidenceBundle as JSON.
        5. Post it to the room so Prosecutor and Defender can cite it.

        You are the ONLY agent allowed to introduce evidence.
        Never fabricate enrichment — mark unknown fields as null.
        """,
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
