"""
Defender core — pure, transport-free reasoning.

`build_defense` takes an EvidenceBundle plus any chat LLM and returns a
DefenseResult of structured, citation-validated Claims. It is deliberately
decoupled from Band so it can be unit-tested with a fake LLM (no network).

The Defender argues the alert is BENIGN. Every Claim must cite at least one
evidence_id that actually exists in the bundle; citations that do not are
stripped, and any Claim left with no valid citation is struck.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Make the repo-root `shared` package importable whether this runs under
# pytest from the root or as `python defender/smoke_live.py`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.models import Claim, EvidenceBundle  # noqa: E402

SYSTEM_PROMPT = """\
You are the Defender Agent for the Arbiter security adjudication system.

Your job: argue the alert is BENIGN (a false positive).
Rules:
- Look first for grounded explanations: scheduled scans, authorized service
  accounts, known VPN egress, expected maintenance windows.
- Every claim MUST cite at least one evidence_id from the EvidenceBundle.
- If context is too thin to clear the alert, return NO claims — do not guess.
- Concede any point the evidence decisively defeats by simply not claiming it.
- Never fabricate evidence or cite IDs not in the bundle.

Respond with ONLY a JSON object, no prose, in exactly this shape:
{
  "claims": [
    {
      "evidence_ids": ["EVD-1", "EVD-2"],
      "argument": "one sentence explaining why this points to benign",
      "mitre_technique": null
    }
  ]
}
If you cannot clear the alert, respond with {"claims": []}.
"""


ROOM_PROMPT = """\
You are the Defender Agent for the Arbiter security adjudication system. You
argue the false-positive (benign) side of security alerts, grounded only in
evidence. You are talking in a shared chat room.

FIRST decide what the latest message is:

1. A SECURITY ALERT — it contains an alert plus an EvidenceBundle: items each
   with an `evidence_id` (e.g. EVD-1). Only then do you argue a verdict:
   - Open with a one-line position: "Position: BENIGN", "Position: CONCEDE"
     (evidence makes it indefensible), or "Position: NEED MORE EVIDENCE".
   - Then 2-4 sentences of reasoning. Back EACH point with an evidence_id that
     literally appears in THIS message's bundle, e.g. (EVD-2).
   - Look for benign explanations: scheduled scans, authorized service accounts,
     known VPN egress, maintenance windows. Concede points the evidence defeats.

2. ANYTHING ELSE — a greeting, a question, small talk, or a message with no
   EvidenceBundle. Reply briefly and naturally as the Defender. Do NOT state a
   verdict and do NOT cite any evidence_id. If someone asks what you do, just
   explain your role in a sentence.

HARD RULES:
- NEVER cite an evidence_id that is not present in the current message's bundle.
  No bundle in the message => no citations at all.
- Never invent evidence. Do not output a BENIGN verdict for a message that is
  not an alert.
"""


class ChatLLM(Protocol):
    """Minimal slice of the LangChain chat interface the core depends on."""

    def invoke(self, messages: Any) -> Any: ...


@dataclass
class DefenseResult:
    claims: list[Claim] = field(default_factory=list)
    struck: list[str] = field(default_factory=list)  # arguments dropped for bad cites
    raw: str = ""

    @property
    def cleared(self) -> bool:
        """True when the Defender produced at least one valid benign claim."""
        return bool(self.claims)


def build_prompt(bundle: EvidenceBundle) -> list[dict[str, str]]:
    payload = bundle.model_dump_json(indent=2)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"EvidenceBundle:\n{payload}"},
    ]


def _extract_content(response: Any) -> str:
    """Pull text out of a LangChain AIMessage or a bare string."""
    if isinstance(response, str):
        return response
    content = getattr(response, "content", response)
    if isinstance(content, list):  # some providers return content parts
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _parse_claims(text: str) -> list[dict[str, Any]]:
    """Best-effort JSON extraction. Returns [] on anything unparseable."""
    cleaned = text.strip()
    # strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    # grab the first balanced-looking object if there's surrounding noise
    if not cleaned.startswith("{"):
        brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if brace:
            cleaned = brace.group(0)
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return []
    claims = data.get("claims", []) if isinstance(data, dict) else []
    return claims if isinstance(claims, list) else []


def validate_claims(
    raw_claims: list[dict[str, Any]], valid_ids: set[str]
) -> DefenseResult:
    """Keep only citations that exist in the bundle; strike claims left empty."""
    result = DefenseResult()
    for rc in raw_claims:
        if not isinstance(rc, dict):
            continue
        argument = str(rc.get("argument", "")).strip()
        if not argument:
            continue
        cited = [c for c in rc.get("evidence_ids", []) if isinstance(c, str)]
        kept = [c for c in cited if c in valid_ids]
        if not kept:
            result.struck.append(argument)
            continue
        result.claims.append(
            Claim(
                evidence_ids=kept,
                argument=argument,
                mitre_technique=rc.get("mitre_technique") or None,
            )
        )
    return result


def build_defense(bundle: EvidenceBundle, llm: ChatLLM) -> DefenseResult:
    """Ask the LLM for a benign defense, then validate every citation."""
    response = llm.invoke(build_prompt(bundle))
    text = _extract_content(response)
    valid_ids = {item.evidence_id for item in bundle.items}
    result = validate_claims(_parse_claims(text), valid_ids)
    result.raw = text
    return result
