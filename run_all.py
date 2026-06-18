"""
Run all Arbiter agents in a single process.
Configured agents start concurrently, while unconfigured/WIP agents are skipped.
"""
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from band import Agent
from band.config import load_agent_config
from band.adapters import LangGraphAdapter

# Agent Adapters and Prompts
from orchestrator.agent import OrchestratorAdapter
from triage.agent import SYSTEM_PROMPT as TRIAGE_SYSTEM_PROMPT, TriagePreprocessor
from triage.tools import TRIAGE_TOOLS
from prosecutor.agent import ProsecutorAdapter
from defender.agent import DefenderAdapter
from judge.agent import SYSTEM_PROMPT as JUDGE_SYSTEM_PROMPT
from diagnostics.agent import DiagnosticsAdapter
from shared.diagnostics import install_diagnostics_logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_all")


def safe_load_config(name: str, config_path: str):
    """Load config safely, returning (None, None) if not found or malformed."""
    try:
        return load_agent_config(name, config_path=config_path)
    except Exception:
        return None, None


def is_valid_config(aid: str, akey: str) -> bool:
    """Check if the agent is configured and not using placeholder values."""
    return bool(aid and akey and not aid.startswith("your-") and not akey.startswith("your-"))


async def main():
    load_dotenv()
    install_diagnostics_logging()

    shared_key = os.getenv("FEATHERLESS_API_KEY")
    shared_model = os.getenv("FEATHERLESS_MODEL") or "Qwen/Qwen3-32B"

    # Fetch per-agent keys falling back to the global key
    orch_fkey = os.getenv("FEATHERLESS_API_KEY_ORCHESTRATOR") or shared_key
    tri_fkey  = os.getenv("FEATHERLESS_API_KEY_TRIAGE") or shared_key
    pro_fkey  = os.getenv("FEATHERLESS_API_KEY_PROSECUTOR") or shared_key
    def_fkey  = os.getenv("FEATHERLESS_API_KEY_DEFENDER") or shared_key
    jud_fkey  = os.getenv("FEATHERLESS_API_KEY_JUDGE") or shared_key

    # Fetch per-agent models falling back to the global model / default
    orch_model = os.getenv("FEATHERLESS_MODEL_ORCHESTRATOR") or shared_model
    tri_model  = os.getenv("FEATHERLESS_MODEL_TRIAGE") or shared_model
    pro_model  = os.getenv("FEATHERLESS_MODEL_PROSECUTOR") or shared_model
    def_model  = os.getenv("FEATHERLESS_MODEL_DEFENDER") or shared_model
    jud_model  = os.getenv("FEATHERLESS_MODEL_JUDGE") or shared_model

    ws_url   = os.getenv("THENVOI_WS_URL")
    rest_url = os.getenv("THENVOI_REST_URL")

    agents = []

    # 1. Orchestrator Agent
    orch_id, orch_key = safe_load_config("my_agent", "orchestrator/agent_config.yaml")
    if is_valid_config(orch_id, orch_key) and orch_fkey:
        orch_llm = ChatOpenAI(
            model=orch_model,
            base_url="https://api.featherless.ai/v1",
            api_key=orch_fkey,
            temperature=0,
        )
        agents.append(
            Agent.create(
                adapter=OrchestratorAdapter(orch_llm, self_id=orch_id),
                agent_id=orch_id,
                api_key=orch_key,
                ws_url=ws_url,
                rest_url=rest_url,
            )
        )
        logger.info("Orchestrator agent configured with model %s.", orch_model)
    else:
        logger.warning("Orchestrator agent is not configured or missing API key.")

    # 2. Triage Agent
    tri_id, tri_key = safe_load_config("triage_agent", "triage/agent_config.yaml")
    if is_valid_config(tri_id, tri_key) and tri_fkey:
        tri_llm = ChatOpenAI(
            model=tri_model,
            base_url="https://api.featherless.ai/v1",
            api_key=tri_fkey,
        )
        tri_adapter = LangGraphAdapter(
            llm=tri_llm,
            checkpointer=InMemorySaver(),
            additional_tools=TRIAGE_TOOLS,
            custom_section=TRIAGE_SYSTEM_PROMPT,
        )
        agents.append(
            Agent.create(
                adapter=tri_adapter,
                agent_id=tri_id,
                api_key=tri_key,
                ws_url=ws_url,
                rest_url=rest_url,
                preprocessor=TriagePreprocessor(),
            )
        )
        logger.info("Triage agent configured with model %s.", tri_model)
    else:
        logger.warning("Triage agent is not configured or missing API key.")

    # 3. Prosecutor Agent
    pro_id, pro_key = safe_load_config("prosecutor_agent", "prosecutor/agent_config.yaml")
    if is_valid_config(pro_id, pro_key) and pro_fkey:
        pro_llm = ChatOpenAI(
            model=pro_model,
            base_url="https://api.featherless.ai/v1",
            api_key=pro_fkey,
            temperature=0.2,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        agents.append(
            Agent.create(
                adapter=ProsecutorAdapter(pro_llm, self_id=pro_id),
                agent_id=pro_id,
                api_key=pro_key,
                ws_url=ws_url,
                rest_url=rest_url,
            )
        )
        logger.info("Prosecutor agent configured with model %s.", pro_model)
    else:
        logger.warning("Prosecutor agent is not configured or missing API key.")

    # 4. Defender Agent
    def_id, def_key = safe_load_config("defender_agent", "defender/agent_config.yaml")
    if is_valid_config(def_id, def_key) and def_fkey:
        def_llm = ChatOpenAI(
            model=def_model,
            base_url="https://api.featherless.ai/v1",
            api_key=def_fkey,
            temperature=0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        agents.append(
            Agent.create(
                adapter=DefenderAdapter(def_llm, self_id=def_id),
                agent_id=def_id,
                api_key=def_key,
                ws_url=ws_url,
                rest_url=rest_url,
            )
        )
        logger.info("Defender agent configured with model %s.", def_model)
    else:
        logger.warning("Defender agent is not configured or missing API key.")

    # 5. Judge Agent
    jud_id, jud_key = safe_load_config("judge_agent", "judge/agent_config.yaml")
    if is_valid_config(jud_id, jud_key) and jud_fkey:
        jud_llm = ChatOpenAI(
            model=jud_model,
            base_url="https://api.featherless.ai/v1",
            api_key=jud_fkey,
        )
        jud_adapter = LangGraphAdapter(
            llm=jud_llm,
            checkpointer=InMemorySaver(),
            custom_section=JUDGE_SYSTEM_PROMPT,
        )
        agents.append(
            Agent.create(
                adapter=jud_adapter,
                agent_id=jud_id,
                api_key=jud_key,
                ws_url=ws_url,
                rest_url=rest_url,
            )
        )
        logger.info("Judge agent configured with model %s.", jud_model)
    else:
        logger.warning("Judge agent is not configured or missing API key (WIP). Skipping Judge activation.")

    # 6. System Diagnostics Agent (Band credentials only — no LLM)
    diag_id, diag_key = safe_load_config(
        "diagnostics_agent", "diagnostics/agent_config.yaml"
    )
    if is_valid_config(diag_id, diag_key):
        agents.append(
            Agent.create(
                adapter=DiagnosticsAdapter(self_id=diag_id),
                agent_id=diag_id,
                api_key=diag_key,
                ws_url=ws_url,
                rest_url=rest_url,
            )
        )
        logger.info("System Diagnostics Agent configured.")
    else:
        logger.warning(
            "System Diagnostics Agent is not configured. "
            "Terminal errors will not appear in Band chat."
        )

    if not agents:
        logger.error("No agents are configured. Exiting.")
        return

    logger.info("Starting %d active agents concurrently...", len(agents))
    await asyncio.gather(*(a.run() for a in agents))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")
        sys.exit(0)
