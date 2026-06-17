"""
Evidence-bundle fixtures for the three demo alerts.

The demo/*.json files are raw Alerts only. The Defender cites evidence_ids,
so to exercise it in isolation we need EvidenceBundles. These hand-authored
bundles mirror what a Triage agent would have enriched, with one decisively
benign case, one ambiguous case, and one decisively malicious case.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from shared.models import Alert, Evidence, EvidenceBundle  # noqa: E402

_DEMO = _REPO_ROOT / "demo"


def load_alert(name: str) -> Alert:
    return Alert(**json.loads((_DEMO / name).read_text()))


def authorized_scanner_bundle() -> EvidenceBundle:
    """ALT-001 — decisively benign: registered scanner in its scheduled window."""
    alert = load_alert("authorized_scanner.json")
    items = [
        Evidence(
            evidence_id="EVD-1",
            source="CMDB",
            description="src_ip 10.10.5.22 is the registered Nessus scanner host.",
            raw={"ip": "10.10.5.22", "role": "vuln_scanner", "owner": "secops"},
        ),
        Evidence(
            evidence_id="EVD-2",
            source="ScanScheduler",
            description="Scheduled scan window 08:00-09:00 UTC Mon-Fri; alert at 08:03 is inside it.",
            raw={"window": "08:00-09:00 UTC", "days": "Mon-Fri"},
        ),
        Evidence(
            evidence_id="EVD-3",
            source="NetFlow",
            description="No follow-on exploitation traffic after the SYN sweep; 312 packets in 4s.",
            raw={"post_scan_sessions": 0},
        ),
    ]
    return EvidenceBundle(alert=alert, items=items)


def impossible_travel_bundle() -> EvidenceBundle:
    """ALT-002 — ambiguous: one login looks VPN-benign, the other does not."""
    alert = load_alert("impossible_travel.json")
    items = [
        Evidence(
            evidence_id="EVD-1",
            source="VPN",
            description="login_2 IP 198.51.100.12 is within the corporate US VPN exit range 198.51.100.0/24.",
            raw={"ip": "198.51.100.12", "vpn_range": "198.51.100.0/24"},
        ),
        Evidence(
            evidence_id="EVD-2",
            source="IAM",
            description="login_2 used an Unknown-Windows device and did NOT pass MFA.",
            raw={"device": "Unknown-Windows", "mfa": False},
        ),
        Evidence(
            evidence_id="EVD-3",
            source="IAM",
            description="login_1 from Manila passed MFA on the user's known MacBook.",
            raw={"device": "MacBook-jsmith", "mfa": True, "geo": "Manila, PH"},
        ),
    ]
    return EvidenceBundle(alert=alert, items=items)


def lsass_dump_bundle() -> EvidenceBundle:
    """ALT-003 — decisively malicious: nothing benign to cite."""
    alert = load_alert("lsass_dump.json")
    items = [
        Evidence(
            evidence_id="EVD-1",
            source="EDR",
            description="rundll32 spawned by cmd.exe opened lsass.exe with full access 0x1FFFFF.",
            raw={"parent": "cmd.exe", "target": "lsass.exe", "access": "0x1FFFFF"},
        ),
        Evidence(
            evidence_id="EVD-2",
            source="EDR",
            description="Unsigned DLL dropped in C:\\Windows\\Temp and loaded by ordinal (#1).",
            raw={"file": "C:\\Windows\\Temp\\srv.dll", "signed": False},
        ),
        Evidence(
            evidence_id="EVD-3",
            source="CMDB",
            description="svc-backup never legitimately accesses LSASS memory in baseline.",
            raw={"account": "FINANCE\\svc-backup", "baseline_lsass_access": False},
        ),
    ]
    return EvidenceBundle(alert=alert, items=items)


ALL_BUNDLES = {
    "authorized_scanner": authorized_scanner_bundle,
    "impossible_travel": impossible_travel_bundle,
    "lsass_dump": lsass_dump_bundle,
}
