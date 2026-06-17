"""Pydantic contracts for the ARBITER Triage Agent."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AlertType = Literal["EDR", "IDS", "AUTH"]
AssetCriticality = Literal["critical", "high", "medium", "low"]
EvidenceSourceType = Literal["raw_log", "cmdb", "baseline", "geo", "lineage", "mitre"]


class RawAlert(BaseModel):
    """Normalized security alert as accepted by downstream adjudication agents."""

    model_config = ConfigDict(extra="allow")

    id: str
    timestamp: datetime
    alert_type: AlertType
    source_host: str
    raw_payload: dict[str, Any]


class Evidence(BaseModel):
    """Single evidence fact with a deterministic citation anchor."""

    evidence_id: str = Field(pattern=r"^EVD-[0-9a-f]{6}-\d{3}$")
    fact: str = Field(min_length=1)
    source_type: EvidenceSourceType
    confidence: float = Field(ge=0.0, le=1.0)
    raw_ref: str | None = None

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_must_be_prefixed(cls, value: str) -> str:
        if not value.startswith("EVD-"):
            raise ValueError("evidence_id must start with EVD-")
        return value


class EvidenceBundle(BaseModel):
    """Versioned, machine-readable case file emitted by Triage."""

    bundle_id: str
    alert_id: str
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    alert_type: AlertType
    asset_criticality: AssetCriticality
    evidence: list[Evidence]
    mitre_candidates: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class TriageSupplementRequest(BaseModel):
    """Judge request for targeted re-triage without mutating existing evidence."""

    original_bundle_id: str
    requested_by: Literal["judge"]
    questions: list[str] = Field(default_factory=list)
    contested_evd_ids: list[str] = Field(default_factory=list)
