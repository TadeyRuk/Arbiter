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

    agent_id, api_key = load_agent_config("my_agent")

    llm = ChatOpenAI(
        model="Qwen/Qwen3-32B",
        base_url="https://api.featherless.ai/v1",
        api_key=os.getenv("FEATHERLESS_API_KEY"),
    )

    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        custom_section="""
        You are the Arbiter Orchestrator for a Security Operations Center adjudication system.

        When a security alert arrives:
        1. Validate and normalize the alert payload.
        2. Open a Band adjudication room for the case.
        3. Delegate to the Triage Agent to enrich the alert and build the evidence bundle.
        4. Once evidence is ready, trigger Prosecutor and Defender agents in parallel.
        5. Hand control to the Judge Agent to validate citations, score severity, and issue a verdict.
        6. If the Judge flags high severity or a disruptive action, escalate to a human analyst before proceeding.
        7. Record the final disposition and close the room.

        You do not perform analysis yourself. You coordinate sequencing, enforce the workflow,
        and ensure no agent acts out of turn. Nothing destructive executes without human approval.
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
