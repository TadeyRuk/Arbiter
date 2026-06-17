"""
Triage Agent — LangChain + Featherless AI
Enriches the alert and builds the evidence bundle.
Every fact gets a stable evidence_id. No other agent introduces evidence.
"""
import asyncio
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from band import Agent
from band.adapters import LangGraphAdapter
from band.config import load_agent_config
from band.preprocessing import DefaultPreprocessor
from band.runtime import AgentTools

try:
    from .evd_generator import EVDGenerator
    from .schemas import Evidence, TriageSupplementRequest
    from .tools import SCENARIOS, TRIAGE_TOOLS, _build_and_post_bundle_impl
except ImportError:  # pragma: no cover - supports `python triage/agent.py`.
    from evd_generator import EVDGenerator
    from schemas import Evidence, TriageSupplementRequest
    from tools import SCENARIOS, TRIAGE_TOOLS, _build_and_post_bundle_impl

import inspect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
EVD_ID_RE = re.compile(r"EVD-[0-9a-f]{6}-\d{3}")
TRIAGE_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = TRIAGE_DIR / "agent_config.yaml"

def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


SYSTEM_PROMPT = """
You are the Triage Agent for the ARBITER security adjudication system.

Your job is to create auditable evidence, not to decide the verdict.

Tool order:
1. Call normalize_alert first with the raw alert payload.
2. Call lookup_asset using the normalized source host, source IP, username, or alert ID.
3. Call get_process_lineage for EDR alerts when a pid and host are available.
4. Call check_behavioral_baseline for the normalized host and event type.
5. Call geo_lookup for AUTH login IPs or any IP where geography matters.
6. Call tag_mitre_candidates with the alert type and observed behaviors.
7. Call build_and_post_bundle last with every tool result collected in all_enrichment.

Rules:
- NEVER introduce a fact that was not returned by a tool call.
- NEVER generate EVD IDs yourself. Only build_and_post_bundle may assign evidence IDs.
- Mark missing, null, or unknown context in open_questions.
- Existing EVD IDs are immutable. Supplements must add new evidence only.
- Do not end by merely returning text to the adapter. Your final action must be
  a call to band_send_message so the result appears in the Band room.
- Before calling band_send_message, call band_get_participants and choose at
  least one valid @mention. Prefer the human requester; for Judge requests,
  mention the Judge if present. If unsure, mention all human participants.
- The band_send_message content must be exactly:
  EVIDENCE_BUNDLE_READY
  {bundle JSON}

When responding to a Judge clarification request, perform only the targeted enrichment
needed for the requested questions and call band_send_message with content:
  TRIAGE_SUPPLEMENT
  {new evidence JSON}
"""


def _json_from_message(message: Any) -> dict[str, Any] | None:
    if isinstance(message, dict):
        for key in ("payload", "content", "text", "body", "message"):
            if key in message:
                nested = _json_from_message(message[key])
                if nested:
                    return nested
        return message

    if not isinstance(message, str):
        return None

    text = message.strip()
    if not text:
        return None
    if not text.startswith("{"):
        json_start = text.find("{")
        if json_start == -1:
            return None
        text = text[json_start:].strip()
    if not text.startswith("{"):
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _collect_existing_evd_ids(agent_input: Any, payload: dict[str, Any]) -> list[str]:
    search_space = [json.dumps(payload, default=str)]
    for item in getattr(agent_input.history, "raw", []) or []:
        search_space.append(json.dumps(item, default=str))
    return sorted(set(EVD_ID_RE.findall("\n".join(search_space))))


def _build_retriage_prompt(payload: dict[str, Any], existing_evidence_ids: list[str]) -> str:
    request = TriageSupplementRequest.model_validate(payload)
    enriched_payload = {
        **payload,
        "questions": request.questions,
        "contested_evd_ids": request.contested_evd_ids,
        "existing_evidence_ids": existing_evidence_ids,
    }
    return (
        "Handle this Judge clarification request as a targeted re-triage turn.\n"
        "Call only the enrichment tools needed for the requested questions.\n"
        "Pass existing_evidence_ids into build_and_post_bundle so new evidence skips "
        "all prior EVD IDs. Do not mutate, reinterpret, or renumber old evidence.\n"
        "Do not only return text. Your final action must call band_get_participants "
        "and then band_send_message with at least one valid @mention.\n"
        "The band_send_message content must be exactly:\n"
        "TRIAGE_SUPPLEMENT\n"
        "{new evidence JSON}\n\n"
        f"Judge request:\n{json.dumps(enriched_payload, indent=2)}"
    )


def _alert_id_for_bundle(bundle_id: str) -> str | None:
    for alert_id in SCENARIOS:
        if f"BND-{EVDGenerator(alert_id).prefix}" == bundle_id:
            return alert_id
    return None


def _next_supplement_evd_id(alert_id: str, used_ids: set[str]) -> str:
    generator = EVDGenerator(alert_id)
    evidence_id = generator.next()
    while evidence_id in used_ids:
        evidence_id = generator.next()
    used_ids.add(evidence_id)
    return evidence_id


def _build_direct_supplement(payload: dict[str, Any], alert_id: str) -> dict[str, Any]:
    request = TriageSupplementRequest.model_validate(payload)
    scenario = SCENARIOS[alert_id]
    original_bundle = _build_and_post_bundle_impl(scenario, alert_id)
    used_ids = {item["evidence_id"] for item in original_bundle["evidence"]}
    used_ids.update(request.contested_evd_ids)

    question_text = " ".join(request.questions).lower()
    evidence: list[dict[str, Any]] = []

    def add(fact: str, source_type: str, confidence: float, raw_ref: str | None) -> None:
        evidence.append(
            Evidence.model_validate(
                {
                    "evidence_id": _next_supplement_evd_id(alert_id, used_ids),
                    "fact": fact,
                    "source_type": source_type,
                    "confidence": confidence,
                    "raw_ref": raw_ref,
                }
            ).model_dump(mode="json")
        )

    if any(term in question_text for term in ("vpn", "tor", "geo", "ip", "country", "exit")):
        for record in scenario.get("geo", {}).values():
            add(
                f"Supplemental GeoIP check confirms {record.get('ip')} has vpn_exit={record.get('is_vpn_exit')} and tor={record.get('is_tor')} in {record.get('city')}, {record.get('country')}.",
                "geo",
                0.8,
                f"geo.{record.get('ip')}",
            )

    if any(term in question_text for term in ("baseline", "normal", "deviation", "expected")):
        baseline = scenario.get("baseline", {})
        add(
            f"Supplemental baseline check confirms baseline_normal={baseline.get('baseline_normal')} with deviation_score={baseline.get('deviation_score')}: {baseline.get('baseline_description')}",
            "baseline",
            0.86,
            "baseline",
        )

    if any(term in question_text for term in ("asset", "cmdb", "owner", "critical", "scanner")):
        asset = scenario.get("asset", {})
        add(
            f"Supplemental CMDB check confirms {asset.get('hostname')} owner={asset.get('owner_team')}, criticality={asset.get('criticality_tier')}, known_scanner={asset.get('is_known_scanner')}.",
            "cmdb",
            0.9,
            "cmdb.asset",
        )

    if any(term in question_text for term in ("lineage", "process", "parent", "lsass", "pid")):
        lineage = scenario.get("lineage", {}).get("lineage", [])
        if lineage:
            chain = " -> ".join(f"{item.get('name')}({item.get('pid')})" for item in lineage)
            add(f"Supplemental process lineage confirms {chain}.", "lineage", 0.88, "lineage")

    if not evidence:
        add(
            "Supplemental triage did not find a scenario fixture field matching the Judge request.",
            "raw_log",
            0.3,
            None,
        )

    return {
        "original_bundle_id": request.original_bundle_id,
        "alert_id": alert_id,
        "requested_by": request.requested_by,
        "questions": request.questions,
        "contested_evd_ids": request.contested_evd_ids,
        "evidence": evidence,
    }


def _mentions_for_reply(tools: Any, agent_id: str, sender_id: str | None = None) -> list[str]:
    participants = getattr(tools, "participants", [])
    if sender_id and sender_id != agent_id:
        for participant in participants:
            if participant.get("id") == sender_id:
                return [
                    participant.get("handle")
                    or participant.get("name")
                    or participant.get("id")
                ]
        return [sender_id]

    mentions: list[str] = []
    for participant in participants:
        participant_id = participant.get("id")
        if participant_id and participant_id != agent_id:
            mentions.append(participant.get("handle") or participant.get("name") or participant_id)
    return mentions[:1]


async def _send_room_visible_content(
    tools: Any,
    room_id: str,
    agent_id: str,
    content: str,
    sender_id: str | None = None,
) -> None:
    mentions = _mentions_for_reply(tools, agent_id, sender_id)
    if mentions:
        try:
            logger.info("Room %s: sending visible Band message with mentions=%s", room_id, mentions)
            await tools.send_message(content=content, mentions=mentions)
            logger.info("Room %s: visible Band message posted", room_id)
            return
        except Exception:
            logger.exception("Room %s: band_send_message failed; falling back to event", room_id)

    logger.warning("Room %s: no valid mention available; sending Band event fallback", room_id)
    await tools.send_event(
        content=content,
        message_type="task",
        metadata={"arbiter_message_type": content.splitlines()[0] if content else "triage"},
    )


class TriagePreprocessor:
    """Band preprocessor that turns Judge clarification JSON into a re-triage prompt."""

    def __init__(self) -> None:
        self._inner = DefaultPreprocessor()

    async def process(self, ctx: Any, event: Any, agent_id: str) -> Any:
        agent_input = await self._inner.process(ctx=ctx, event=event, agent_id=agent_id)
        if agent_input is None:
            return None

        # Check if spoken to
        content_lower = (agent_input.msg.content or "").lower()
        tools = agent_input.tools
        parts = tools.get_participants()
        if inspect.isawaitable(parts):
            parts = await parts
        
        self_handle = None
        for p in parts or []:
            if _field(p, "id") == agent_id:
                self_handle = _field(p, "handle") or _field(p, "name")
                break
                
        is_spoken_to = False
        if self_handle and self_handle.lower() in content_lower:
            is_spoken_to = True
        elif "triage" in content_lower:
            is_spoken_to = True
            
        if not is_spoken_to:
            logger.info("Triage agent ignoring message %s (not spoken to)", agent_input.msg.id)
            return None

        payload = _json_from_message(agent_input.msg.content)
        if not payload or payload.get("type") != "JUDGE_REQUESTS_CLARIFICATION":
            return agent_input

        existing_ids = _collect_existing_evd_ids(agent_input, payload)
        prompt = _build_retriage_prompt(payload, existing_ids)
        logger.info(
            "Room %s: converted Judge clarification into targeted re-triage prompt",
            agent_input.room_id,
        )
        return replace(agent_input, msg=replace(agent_input.msg, content=prompt))

async def main():
    load_dotenv(TRIAGE_DIR / ".env")
    load_dotenv(TRIAGE_DIR.parent / ".env", override=False)

    agent_id, api_key = load_agent_config("triage_agent", config_path=AGENT_CONFIG_PATH)

    model = (
        os.getenv("FEATHERLESS_MODEL_TRIAGE")
        or os.getenv("FEATHERLESS_MODEL")
        or "Qwen/Qwen3-32B"
    )
    llm = ChatOpenAI(
        model=model,
        base_url="https://api.featherless.ai/v1",
        api_key=os.getenv("FEATHERLESS_API_KEY_TRIAGE") or os.getenv("FEATHERLESS_API_KEY"),
    )

    adapter = LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        additional_tools=TRIAGE_TOOLS,
        custom_section=SYSTEM_PROMPT,
    )

    agent = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
        preprocessor=TriagePreprocessor(),
    )

    await agent.run()

if __name__ == "__main__":
    asyncio.run(main())
