"""
Defender Agent — LangChain + open model via Featherless AI
Argues the alert is a false positive, grounded in evidence.
Different vendor = genuinely different reasoner from the Prosecutor.
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

async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("defender_agent")

    llm = ChatOpenAI(
        model="Qwen/Qwen3-32B",
        base_url="https://api.featherless.ai/v1",
        api_key=os.getenv("FEATHERLESS_API_KEY"),
    )

    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section="""
        You are the Defender Agent for the Arbiter security adjudication system.

        Your job: argue the alert is BENIGN (false positive).
        Rules:
        - Look first for grounded explanations: scheduled scans, authorized service accounts,
          known VPN egress, expected maintenance windows.
        - Every claim MUST cite at least one evidence_id from the EvidenceBundle.
        - If context is too thin to clear the alert, say so explicitly — do not guess.
        - Concede any point the evidence decisively defeats.
        - Never fabricate evidence or cite IDs not in the bundle.
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
