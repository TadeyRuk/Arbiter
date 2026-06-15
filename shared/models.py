from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(str, Enum):
    REAL_INCIDENT = "real_incident"
    FALSE_POSITIVE = "false_positive"
    ESCALATE_HUMAN = "escalate_human"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class Alert(BaseModel):
    alert_id: str
    source: str                          # EDR, IDS, IAM, etc.
    rule_name: str
    timestamp: str
    asset_id: str
    asset_criticality: str               # low / medium / high / critical
    raw_payload: dict[str, Any]


class Evidence(BaseModel):
    evidence_id: str                     # stable ID used in citations
    source: str
    description: str
    raw: dict[str, Any]


class EvidenceBundle(BaseModel):
    alert: Alert
    items: list[Evidence] = Field(default_factory=list)


class Claim(BaseModel):
    evidence_ids: list[str]              # must reference valid EvidenceBundle IDs
    argument: str
    mitre_technique: str | None = None


class SeverityScore(BaseModel):
    evidence_strength: int = Field(ge=0, le=10)
    asset_criticality: int = Field(ge=0, le=10)
    mitre_severity: int = Field(ge=0, le=10)
    blast_radius: int = Field(ge=0, le=10)
    base_rate: int = Field(ge=0, le=10)

    @property
    def total(self) -> float:
        weights = [0.3, 0.25, 0.2, 0.15, 0.1]
        scores = [
            self.evidence_strength,
            self.asset_criticality,
            self.mitre_severity,
            self.blast_radius,
            self.base_rate,
        ]
        return sum(w * s for w, s in zip(weights, scores))


class Disposition(BaseModel):
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity
    severity_score: SeverityScore
    prosecutor_claims: list[Claim]
    defender_claims: list[Claim]
    struck_claims: list[str]            # claim arguments struck for missing citations
    reasoning: str
    requires_human_approval: bool
    human_decision: str | None = None   # set after human reviews
