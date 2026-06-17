"""
Run Orchestrator + Defender in a single process.

Usage (from project root):
    python run_all.py
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from band import Agent
from band.config import load_agent_config

from orchestrator.agent import OrchestratorAdapter
from defender.agent import DefenderAdapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_all")


async def main():
    load_dotenv()

    shared_key = os.getenv("FEATHERLESS_API_KEY")
    orch_featherless_key = os.getenv("FEATHERLESS_API_KEY_ORCHESTRATOR", shared_key)
    def_featherless_key  = os.getenv("FEATHERLESS_API_KEY_DEFENDER",     shared_key)
    ws_url   = os.getenv("THENVOI_WS_URL")
    rest_url = os.getenv("THENVOI_REST_URL")

    orch_id, orch_key = load_agent_config(
        "my_agent", config_path="orchestrator/agent_config.yaml"
    )
    def_id, def_key = load_agent_config(
        "defender_agent", config_path="defender/agent_config.yaml"
    )

    orch_llm = ChatOpenAI(
        model="Qwen/Qwen3-32B",
        base_url="https://api.featherless.ai/v1",
        api_key=orch_featherless_key,
        temperature=0,
    )
    def_llm = ChatOpenAI(
        model="Qwen/Qwen3-32B",
        base_url="https://api.featherless.ai/v1",
        api_key=def_featherless_key,
        temperature=0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    orch_agent = Agent.create(
        adapter=OrchestratorAdapter(orch_llm, self_id=orch_id),
        agent_id=orch_id,
        api_key=orch_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )
    def_agent = Agent.create(
        adapter=DefenderAdapter(def_llm, self_id=def_id),
        agent_id=def_id,
        api_key=def_key,
        ws_url=ws_url,
        rest_url=rest_url,
    )

    logger.info("Starting Orchestrator (%s) + Defender (%s)", orch_id, def_id)
    await asyncio.gather(orch_agent.run(), def_agent.run())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)
