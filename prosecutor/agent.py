"""
Prosecutor Agent — CrewAI + Claude Sonnet (Anthropic)
Argues the alert is a real incident, citing only evidence IDs from the bundle.
"""
import asyncio
import logging
import os
from dotenv import load_dotenv
from band import Agent
from band.adapters import CrewAIAdapter
from band.config import load_agent_config

logging.basicConfig(level=logging.INFO)

async def main():
    load_dotenv()

    agent_id, api_key = load_agent_config("prosecutor_agent")

    # TODO: configure CrewAI agent with Claude Sonnet
    # from crewai import Agent as CrewAgent
    # from langchain_anthropic import ChatAnthropic
    # llm = ChatAnthropic(model="claude-sonnet-4-6", api_key=os.getenv("ANTHROPIC_API_KEY"))
    # crew_agent = CrewAgent(role="Prosecutor", goal="...", llm=llm, ...)

    adapter = CrewAIAdapter(
        # crew_agent=crew_agent,
        custom_section="""
        You are the Prosecutor Agent for the Arbiter security adjudication system.

        Your job: argue that the alert is a REAL INCIDENT.
        Rules:
        - Every claim MUST cite at least one evidence_id from the EvidenceBundle.
        - Map behaviors to MITRE ATT&CK techniques where applicable.
        - You get ONE rebuttal after the Defender responds.
        - If the evidence decisively defeats a point, concede it — do not argue against proof.
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
