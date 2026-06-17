"""
Prosecutor core - pure, transport-free reasoning.

`build_prosecution` takes an EvidenceBundle plus any chat LLM and returns a
ProsecutionResult of structured, citation-validated Claims. It is deliberately
decoupled from Band so it can be unit-tested with a fake LLM (no network).

The Prosecutor argues the alert is a REAL INCIDENT. Every Claim must cite at
least one evidence_id that actually exists in the bundle; citations that do
not are stripped, and any Claim left with no valid citation is struck.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.models import Claim, EvidenceBundle  # noqa: E402

SYSTEM_PROMPT = """\
You are the Prosecutor Agent for the Arbiter security adjudication system.

Your job: argue the alert is a REAL INCIDENT (malicious activity).
Rules:
- Map behaviors to MITRE ATT&CK techniques where applicable.
- Every claim MUST cite at least one evidence_id from the EvidenceBundle.
- If the evidence decisively defeats a point, concede it by simply not claiming it.
- If context is too thin to support a real-incident case, return NO claims - do not guess.
- Never fabricate evidence or cite IDs not in the bundle.

Respond with ONLY a JSON object, no prose, in exactly this shape:
{
  "claims": [
    {
      "evidence_ids": ["EVD-1", "EVD-2"],
      "argument": "one sentence explaining why this supports a real incident",
      "mitre_technique": "T1055"
    }
  ]
}
If you cannot support a malicious interpretation, respond with {"claims": []}.
"""


ROOM_PROMPT = """\
You are the Prosecutor Agent for the Arbiter security adjudication system. You
argue the real-incident (malicious) side of security alerts, grounded only in
evidence. You are talking in a shared chat room.

FIRST decide what the latest message is:

1. A SECURITY ALERT - it contains an alert plus an EvidenceBundle: items each
   with an `evidence_id` (e.g. EVD-1). Only then do you argue a verdict:
   - Open with a one-line position: "Position: REAL INCIDENT", "Position: CONCEDE"
     (the evidence makes the malicious theory indefensible), or
     "Position: NEED MORE EVIDENCE".
   - Then 2-4 sentences of reasoning. Back EACH point with an evidence_id that
     literally appears in THIS message's bundle, e.g. (EVD-2).
   - Map behaviors to MITRE ATT&CK techniques where applicable.
   - Concede points the evidence defeats.

2. ANYTHING ELSE - a greeting, a question, small talk, or a message with no
   EvidenceBundle. Reply briefly and naturally as the Prosecutor. Do NOT state
   a verdict and do NOT cite any evidence_id. If someone asks what you do, just
   explain your role in a sentence.

HARD RULES:
- NEVER cite an evidence_id that is not present in the current message's bundle.
  No bundle in the message => no citations at all.
- Never invent evidence. Do not output a REAL INCIDENT verdict for a message
  that is not an alert.
"""


class ChatLLM(Protocol):
    """Minimal slice of the LangChain chat interface the core depends on."""

    def invoke(self, messages: Any) -> Any: ...


@dataclass
class ProsecutionResult:
    claims: list[Claim] = field(default_factory=list)
    struck: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def proven(self) -> bool:
        """True when the Prosecutor produced at least one valid malicious claim."""
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
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _parse_claims(text: str) -> list[dict[str, Any]]:
    """Best-effort JSON extraction. Returns [] on anything unparseable."""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
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


def validate_claims(raw_claims: list[dict[str, Any]], valid_ids: set[str]) -> ProsecutionResult:
    """Keep only citations that exist in the bundle; strike claims left empty."""
    result = ProsecutionResult()
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


def build_prosecution(bundle: EvidenceBundle, llm: ChatLLM) -> ProsecutionResult:
    """Ask the LLM for a malicious case, then validate every citation."""
    response = llm.invoke(build_prompt(bundle))
    text = _extract_content(response)
    valid_ids = {item.evidence_id for item in bundle.items}
    result = validate_claims(_parse_claims(text), valid_ids)
    result.raw = text
    return result