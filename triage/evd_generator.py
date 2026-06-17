"""Deterministic evidence ID generation for ARBITER."""

from __future__ import annotations

import hashlib


class EVDGenerator:
    """Generate stable, sequential evidence IDs for a single alert."""

    def __init__(self, alert_id: str):
        self.prefix = hashlib.sha256(alert_id.encode("utf-8")).hexdigest()[:6]
        self.sequence = 1

    def next(self) -> str:
        evidence_id = f"EVD-{self.prefix}-{self.sequence:03d}"
        self.sequence += 1
        return evidence_id
