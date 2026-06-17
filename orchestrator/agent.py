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
import json
import logging
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from band import Agent
from band.config import load_agent_config
from band.core.simple_adapter import SimpleAdapter
from band.converters.langchain import LangChainHistoryConverter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")
ORCHESTRATOR_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = ORCHESTRATOR_DIR / "agent_config.yaml"

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)

_ALERT_KEYS = ('"alert_id"', '"rule_name"', '"raw_payload"')
_BUNDLE_MARKERS = ('"evidence_id"', '"EVD-', "EVD-")
_PROSECUTION_MARKERS = ("MITRE ATT&CK", "real_incident", "REAL INCIDENT", "ATT&CK T")
_DEFENSE_MARKERS = ("false_positive", "BENIGN", "false positive", "FALSE POSITIVE")
_DISPOSITION_MARKERS = ('"verdict"', '"confidence"', '"severity_score"', '"requires_human_approval"')


_AGENT_NAMES = ("triage", "prosecutor", "defender", "judge")
_AGENT_HANDLE_SUFFIXES = (
    "/arbiter-orchestrator",
    "/arbiter-triage",
    "/arbiter-prosecutor",
    "/arbiter-defender",
    "/arbiter-judge",
)

# Tokens are ~4 chars; 600 chars ≈ 150 tokens — long enough to warrant deep reasoning.
_THINKING_CHAR_THRESHOLD = 600


def _needs_thinking(text: str) -> bool:
    """Heuristic: enable Qwen3 thinking when the message warrants deep analysis.

    Triggers:
    - Contains an alert payload (known JSON keys).
    - Long message — complex inquiry needs reasoning before routing.
    - References multiple agents — cross-agent coordination is non-trivial.
    - Deeply nested JSON — structured complexity signals a real case, not chatter.
    """
    if any(k in text for k in _ALERT_KEYS):
        return True
    if len(text) >= _THINKING_CHAR_THRESHOLD:
        return True
    agents_mentioned = sum(1 for name in _AGENT_NAMES if name in text.lower())
    if agents_mentioned >= 2:
        return True
    # Nested JSON: two or more levels of braces/brackets suggest a complex payload.
    if text.count("{") >= 2 or text.count("[") >= 2:
        return True
    return False

SYSTEM_PROMPT = """\
You are the Arbiter Orchestrator for a Security Operations Center adjudication system.

You coordinate the workflow — you do not perform analysis or issue verdicts.

Agents in this system:
- Triage: enriches alerts, builds the EvidenceBundle with stable evidence_ids. Handle ends with /arbiter-triage.
- Prosecutor: argues the alert is a real incident. Handle ends with /arbiter-prosecutor.
- Defender: argues the alert is a false positive. Handle ends with /arbiter-defender.
- Judge: validates citations, scores severity, issues the Disposition. Handle ends with /arbiter-judge.

Workflow:
1. When an alert JSON arrives, acknowledge it and open the case.
2. Forward the alert to the Triage agent.
3. Once Triage posts the EvidenceBundle, forward it to both the Prosecutor and Defender in parallel.
4. Once both Prosecutor and Defender have posted their arguments, forward the case to the Judge.
5. Once the Judge issues the Disposition, close the case.

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
    "2. 🔍 Triage: enrich + build EvidenceBundle *(ready)*\n"
    "3. ⚔️  Prosecutor + 🛡️ Defender: argue both sides in parallel *(ready)*\n"
    "4. ⚖️  Judge: validate citations, score severity, issue verdict *(WIP)*\n\n"
    "Paste an alert JSON to begin."
)


def _clean(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def _field(p, key):
    if isinstance(p, dict):
        return p.get(key)
    return getattr(p, key, None)


def _message_content(msg) -> str:
    return getattr(msg, "content", None) or msg.format_for_llm()


def _json_payload(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        start = raw.find("{")
        if start == -1:
            return None
        raw = raw[start:]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _is_explicit_alert(text: str) -> bool:
    payload = _json_payload(text)
    if payload:
        return bool(payload.get("alert_id") and payload.get("rule_name"))
    return (text or "").strip() in {"DEMO-SCAN-001", "DEMO-TRAVEL-001", "DEMO-LSASS-001"}


def _is_agent_handle(handle: str | None) -> bool:
    return bool(handle and handle.endswith(_AGENT_HANDLE_SUFFIXES))


class OrchestratorAdapter(SimpleAdapter):
    """Coordinate the adjudication workflow and post all messages explicitly."""

    def __init__(self, llm, self_id: str):
        super().__init__(history_converter=LangChainHistoryConverter())
        self.llm = llm
        self.self_id = self_id
        # Case state machine — persists across on_message calls.
        self._phase = "idle"  # idle | triage | debate | judging | done
        self._debate_sides = set()
        self._case_summary = []

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

    async def _humans(self, tools) -> list[str]:
        handles = []
        for p in await self._participants(tools):
            handle = _field(p, "handle") or _field(p, "name")
            if handle and not _is_agent_handle(handle):
                handles.append(handle)
        return handles

    async def _find_agent(self, tools, handle_suffix: str) -> str | None:
        for p in await self._participants(tools):
            handle = _field(p, "handle") or _field(p, "name")
            if handle and handle.endswith(handle_suffix):
                return handle
        return None

    async def _get_sender_role(self, tools, sender_id: str) -> str | None:
        for p in await self._participants(tools):
            if _field(p, "id") == sender_id:
                handle = _field(p, "handle") or _field(p, "name") or ""
                if handle.endswith("/arbiter-triage"):
                    return "triage"
                elif handle.endswith("/arbiter-prosecutor"):
                    return "prosecutor"
                elif handle.endswith("/arbiter-defender"):
                    return "defender"
                elif handle.endswith("/arbiter-judge"):
                    return "judge"
        return None

    def _reset_case(self):
        self._phase = "idle"
        self._debate_sides = set()
        self._case_summary = []

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
        logger.info("[ORCHESTRATOR] phase=%s handling %s in %s", self._phase, msg.id, room_id)
        
        # 0. Ignore messages sent by self
        if msg.sender_id == self.self_id:
            logger.info("[ORCHESTRATOR] ignoring message %s (sent by self)", msg.id)
            return

        user_text = msg.format_for_llm()
        current_text = _message_content(msg)
        messages = [("system", SYSTEM_PROMPT), *(history or []), ("user", user_text)]

        try:
            human_mentions = await self._humans(tools)

            if is_session_bootstrap:
                await tools.send_message(content=WELCOME, mentions=human_mentions or None)
                return

            sender_role = await self._get_sender_role(tools, msg.sender_id)

            # Ignore messages from other agents when in idle or done phase
            if self._phase in ("idle", "done") and sender_role is not None:
                logger.info("[ORCHESTRATOR] ignoring message %s from agent %s in %s phase", msg.id, sender_role, self._phase)
                return

            # ── Phase 1: Alert received ──────────────────────────────────────
            is_alert = sender_role is None and _is_explicit_alert(current_text)
            if is_alert:
                self._reset_case()
                self._phase = "triage"
                self._case_summary.append(current_text)

                thinking = _needs_thinking(current_text)
                response = await self.llm.ainvoke(
                    messages,
                    extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
                )
                content = _clean(getattr(response, "content", str(response)))
                if not content:
                    content = "**[ORCHESTRATOR]** New alert received. Opening case and routing to Triage."
                await tools.send_message(content=content, mentions=human_mentions or None)

                triage = await self._find_agent(tools, "/arbiter-triage")
                if triage:
                    await tools.send_message(
                        content=(
                            "**[ORCHESTRATOR → TRIAGE]** New alert. "
                            "Please enrich and produce the EvidenceBundle.\n\n" + current_text
                        ),
                        mentions=[triage],
                    )
                    logger.info("[ORCHESTRATOR] forwarded alert to Triage (%s)", triage)
                else:
                    await tools.send_message(
                        content=(
                            "⚠️ Triage agent not found in room. "
                            "Add the agent whose handle ends with `/arbiter-triage` and resend."
                        ),
                        mentions=human_mentions or None,
                    )
                return

            # ── Phase 2: EvidenceBundle from Triage ─────────────────────────
            is_bundle = (sender_role == "triage") or ("EVIDENCE_BUNDLE_READY" in user_text) or (any(k in user_text for k in _BUNDLE_MARKERS) and self._phase == "triage")
            if is_bundle and self._phase == "triage":
                self._phase = "debate"
                self._case_summary.append(user_text)

                await tools.send_message(
                    content="**[ORCHESTRATOR]** EvidenceBundle received. Forwarding to Prosecutor and Defender.",
                    mentions=human_mentions or None,
                )

                prosecutor = await self._find_agent(tools, "/arbiter-prosecutor")
                defender = await self._find_agent(tools, "/arbiter-defender")
                missing = [r for r, h in [("Prosecutor", prosecutor), ("Defender", defender)] if not h]

                if missing:
                    await tools.send_message(
                        content=(
                            f"⚠️ Missing from room: {', '.join(missing)}. "
                            "Add the missing agents and restart the case."
                        ),
                        mentions=human_mentions or None,
                    )
                    return

                await tools.send_message(
                    content=(
                        "**[ORCHESTRATOR → PROSECUTOR]** "
                        "EvidenceBundle ready. Argue the real-incident position.\n\n" + user_text
                    ),
                    mentions=[prosecutor],
                )
                await tools.send_message(
                    content=(
                        "**[ORCHESTRATOR → DEFENDER]** "
                        "EvidenceBundle ready. Argue the false-positive position.\n\n" + user_text
                    ),
                    mentions=[defender],
                )
                logger.info("[ORCHESTRATOR] forwarded bundle to Prosecutor + Defender")
                return

            # ── Phase 3: Debate — collect both sides ─────────────────────────
            if self._phase == "debate":
                if "Internal error" in user_text:
                    logger.warning(
                        "[ORCHESTRATOR] received agent error from %s; waiting for a real argument",
                        sender_role or "unknown sender",
                    )
                    return

                is_prosecution = (sender_role == "prosecutor") or ("REAL INCIDENT" in user_text)
                is_defense = (sender_role == "defender") or ("BENIGN" in user_text)

                if is_prosecution:
                    self._debate_sides.add("prosecution")
                    self._case_summary.append(user_text)
                    logger.info("[ORCHESTRATOR] prosecution argument received")

                if is_defense:
                    self._debate_sides.add("defense")
                    self._case_summary.append(user_text)
                    logger.info("[ORCHESTRATOR] defense argument received")

                if self._debate_sides >= {"prosecution", "defense"}:
                    self._phase = "judging"

                    await tools.send_message(
                        content="**[ORCHESTRATOR]** Both sides have argued. Forwarding to Judge.",
                        mentions=human_mentions or None,
                    )

                    judge = await self._find_agent(tools, "/arbiter-judge")
                    if judge:
                        case_text = "\n\n---\n\n".join(self._case_summary)
                        await tools.send_message(
                            content=(
                                "**[ORCHESTRATOR → JUDGE]** "
                                "Complete case file follows. Please validate citations, "
                                "score severity, and issue a Disposition.\n\n" + case_text
                            ),
                            mentions=[judge],
                        )
                        logger.info("[ORCHESTRATOR] forwarded case to Judge")
                    else:
                        await tools.send_message(
                            content=(
                                "⚠️ **[ORCHESTRATOR]** Judge agent not found in room. "
                                "Adjudicating case internally (fallback mode)."
                            ),
                            mentions=human_mentions or None,
                        )
                        # Fallback Judge Logic
                        try:
                            from judge.agent import SYSTEM_PROMPT as JUDGE_SYSTEM_PROMPT
                            from judge.agent import _clean as judge_clean
                        except ImportError:
                            JUDGE_SYSTEM_PROMPT = """\
You are the Judge Agent for the Arbiter security adjudication system.

You receive the Prosecutor's argument, the Defender's argument, and the original EvidenceBundle.

Responsibilities:
1. CITATION VALIDATION: Strike any claim citing an evidence_id not present in the EvidenceBundle.
   A struck claim cannot be used in the verdict.
2. EVIDENCE REQUEST: If a decisive question is unanswered, send the case back to Triage ONCE.
   If still unanswered after re-enrichment, proceed with available evidence.
3. SEVERITY SCORING (0-10 each dimension):
   - evidence_strength (30%)
   - asset_criticality (25%)
   - mitre_severity (20%)
   - blast_radius (15%)
   - base_rate (10%)
   Final score = weighted sum.
4. VERDICT: Issue one of:
   - real_incident — confirmed threat
   - false_positive — benign activity
   - escalate_human — evidence insufficient to decide; human SOC analyst needed
   - needs_more_evidence — send back to Triage for one more enrichment pass
5. ESCALATION: Set requires_human_approval=true when:
   - verdict is real_incident AND severity score >= 7, OR
   - any proposed action is disruptive (isolate host, disable credential, block production IP)
   Nothing destructive executes without human sign-off.

Output a Disposition JSON:
{
  "verdict": "<verdict>",
  "confidence": 0.0-1.0,
  "severity_score": 0.0-10.0,
  "score_breakdown": {
    "evidence_strength": 0.0,
    "asset_criticality": 0.0,
    "mitre_severity": 0.0,
    "blast_radius": 0.0,
    "base_rate": 0.0
  },
  "struck_claims": ["EVD-x cited by Prosecutor claim 2 — not in bundle"],
  "reasoning": "...",
  "requires_human_approval": false
}

Be calibrated. An honest low-confidence verdict beats a false certainty.
"""
                            import re
                            _THINK_FALLBACK = re.compile(r"<think>.*?</think>", re.DOTALL)
                            def judge_clean(text: str) -> str:
                                return _THINK_FALLBACK.sub("", text or "").strip()

                        case_text = "\n\n---\n\n".join(self._case_summary)
                        judge_messages = [("system", JUDGE_SYSTEM_PROMPT), ("user", case_text)]

                        logger.info("[ORCHESTRATOR] running fallback judge adjudication...")
                        response = await self.llm.ainvoke(
                            judge_messages,
                            extra_body={"chat_template_kwargs": {"enable_thinking": True}},
                        )
                        disposition = judge_clean(getattr(response, "content", str(response)))
                        if not disposition:
                            disposition = "Could not produce a Disposition from the available arguments."

                        await tools.send_message(content=disposition, mentions=human_mentions or None)
                        logger.info("[ORCHESTRATOR] fallback adjudication complete")

                        self._phase = "done"
                        await tools.send_message(
                            content="**[ORCHESTRATOR]** Case closed (internal fallback verdict).",
                            mentions=human_mentions or None,
                        )
                return

            # ── Phase 4: Disposition from Judge ──────────────────────────────
            is_disposition = (sender_role == "judge") or any(k in user_text for k in ('"verdict"', '"confidence"', '"severity_score"', '"requires_human_approval"'))
            if self._phase == "judging" and is_disposition:
                self._phase = "done"
                thinking = _needs_thinking(user_text)
                response = await self.llm.ainvoke(
                    messages,
                    extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
                )
                content = _clean(getattr(response, "content", str(response)))
                if not content:
                    content = "**[ORCHESTRATOR]** Case closed. Judge has issued the Disposition above."
                await tools.send_message(content=content, mentions=human_mentions or None)
                logger.info("[ORCHESTRATOR] case closed")
                return

            # ── Default: general coordination message ─────────────────────────
            if self._phase in ("idle", "done"):
                await tools.send_message(
                    content="Acknowledged. Paste an alert JSON with `alert_id` and `rule_name` to open a case.",
                    mentions=human_mentions or None,
                )

        except Exception:
            logger.exception("[ORCHESTRATOR] failed on %s", msg.id)
            try:
                await tools.send_message(
                    content="Internal error in Orchestrator; see agent logs.",
                    mentions=(await self._humans(tools)) or None,
                )
            except Exception:
                logger.exception("[ORCHESTRATOR] error-reply also failed on %s", msg.id)


async def main():
    load_dotenv()

    agent_id, band_api_key = load_agent_config("my_agent", config_path=AGENT_CONFIG_PATH)

    model = (
        os.getenv("FEATHERLESS_MODEL_ORCHESTRATOR")
        or os.getenv("FEATHERLESS_MODEL")
        or "Qwen/Qwen3-32B"
    )
    featherless_api_key = (
        os.getenv("FEATHERLESS_API_KEY_ORCHESTRATOR")
        or os.getenv("FEATHERLESS_API_KEY")
    )
    if not featherless_api_key:
        raise RuntimeError("Missing FEATHERLESS_API_KEY_ORCHESTRATOR or FEATHERLESS_API_KEY")

    llm = ChatOpenAI(
        model=model,
        base_url="https://api.featherless.ai/v1",
        api_key=featherless_api_key,
        temperature=0,
    )

    agent = Agent.create(
        adapter=OrchestratorAdapter(llm, self_id=agent_id),
        agent_id=agent_id,
        api_key=band_api_key,
        ws_url=os.getenv("THENVOI_WS_URL"),
        rest_url=os.getenv("THENVOI_REST_URL"),
    )

    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
