"""Mock enrichment tools for the ARBITER Triage Agent."""

from __future__ import annotations

import ipaddress
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from langchain_core.tools import tool
except ModuleNotFoundError:  # pragma: no cover - local smoke tests may not install LangChain.
    def tool(func=None, **_kwargs):
        if func is None:
            return lambda wrapped: wrapped
        return func

try:
    from .evd_generator import EVDGenerator
    from .schemas import EvidenceBundle, RawAlert
except ImportError:  # pragma: no cover - supports `python triage/smoke_test.py`.
    from evd_generator import EVDGenerator
    from schemas import EvidenceBundle, RawAlert


SCENARIO_DIR = Path(__file__).parent / "scenarios"


def _load_scenarios() -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for path in sorted(SCENARIO_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        alert_id = data.get("alert_id")
        if alert_id:
            scenarios[alert_id] = data
    return scenarios


SCENARIOS = _load_scenarios()


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    raise ValueError("Expected a JSON object or dict")


def _find_by_alert_id(alert_id: str | None) -> dict[str, Any] | None:
    if not alert_id:
        return None
    for fixture_id, data in SCENARIOS.items():
        if alert_id.startswith(fixture_id) or fixture_id.startswith(alert_id):
            return data
    return None


def _raw_payload_from_fixture(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("raw_alert", {}).get("raw_payload", {})


def _find_by_identifier(identifier: str | None) -> dict[str, Any] | None:
    if not identifier:
        return None
    lowered = str(identifier).lower()
    by_alert = _find_by_alert_id(str(identifier))
    if by_alert:
        return by_alert

    for data in SCENARIOS.values():
        asset = data.get("asset", {})
        raw_alert = data.get("raw_alert", {})
        raw_payload = _raw_payload_from_fixture(data)
        candidates = {
            data.get("alert_id"),
            asset.get("hostname"),
            asset.get("ip"),
            raw_alert.get("source_host"),
            raw_payload.get("src_ip"),
            raw_payload.get("src_host"),
            raw_payload.get("host"),
            raw_payload.get("asset_id"),
            raw_payload.get("user"),
        }
        for login_key in ("login_1", "login_2"):
            login = raw_payload.get(login_key)
            if isinstance(login, dict):
                candidates.add(login.get("ip"))
                candidates.add(login.get("device"))
        if lowered in {str(candidate).lower() for candidate in candidates if candidate is not None}:
            return data
    return None


def _detect_alert_type(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or payload.get("alert_type") or payload.get("type") or "").upper()
    if source in {"EDR", "IDS", "AUTH"}:
        return source
    if source in {"IAM", "IDP", "LOGIN"}:
        return "AUTH"
    if "login_1" in payload or "login_2" in payload or "mfa" in payload:
        return "AUTH"
    if "target_process" in payload or "process" in payload or "pid" in payload:
        return "EDR"
    if "src_ip" in payload and ("dst_ip" in payload or "ports_scanned" in payload):
        return "IDS"
    return "IDS"


def _source_host(payload: dict[str, Any], alert_type: str) -> str:
    if payload.get("source_host"):
        return str(payload["source_host"])
    if payload.get("host"):
        return str(payload["host"])
    if payload.get("src_host"):
        return str(payload["src_host"])
    if alert_type == "IDS" and payload.get("src_ip"):
        return str(payload["src_ip"])
    if alert_type == "AUTH" and payload.get("user"):
        return str(payload["user"])
    return str(payload.get("asset_id") or payload.get("hostname") or "unknown-source")


def _normalize_alert_impl(raw_payload: dict[str, Any]) -> dict[str, Any]:
    payload = _coerce_dict(raw_payload)
    if "raw_alert" in payload:
        return RawAlert.model_validate(payload["raw_alert"]).model_dump(mode="json")

    alert_id = payload.get("alert_id") or payload.get("id")
    fixture = _find_by_alert_id(alert_id)
    if fixture:
        return RawAlert.model_validate(fixture["raw_alert"]).model_dump(mode="json")

    inner_payload = payload.get("raw_payload")
    if isinstance(inner_payload, dict):
        merged_payload = {**inner_payload}
        for key in ("alert_id", "id", "timestamp", "source", "alert_type", "rule_name"):
            if key in payload and key not in merged_payload:
                merged_payload[key] = payload[key]
        payload = merged_payload

    alert_type = _detect_alert_type(payload)
    timestamp = payload.get("timestamp") or datetime.now(UTC).isoformat()
    normalized = {
        "id": str(payload.get("alert_id") or payload.get("id") or "UNKNOWN-ALERT"),
        "timestamp": timestamp,
        "alert_type": alert_type,
        "source_host": _source_host(payload, alert_type),
        "raw_payload": payload,
    }
    return RawAlert.model_validate(normalized).model_dump(mode="json")


def _lookup_asset_impl(identifier: str) -> dict[str, Any]:
    fixture = _find_by_identifier(identifier)
    if fixture:
        return dict(fixture["asset"])

    ip_value = None
    try:
        ip_value = str(ipaddress.ip_address(str(identifier)))
    except ValueError:
        pass

    return {
        "hostname": str(identifier),
        "ip": ip_value,
        "owner_team": "unknown",
        "environment": "unknown",
        "criticality_tier": "low",
        "is_known_scanner": False,
    }


def _get_process_lineage_impl(pid: int | None = None, host: str = "") -> dict[str, Any]:
    if pid is None:
        return {"lineage": [], "available": False}

    fixture = _find_by_identifier(host)
    if fixture and fixture.get("lineage"):
        return dict(fixture["lineage"])

    return {"lineage": [], "available": False}


def _check_behavioral_baseline_impl(host: str, event_type: str) -> dict[str, Any]:
    fixture = _find_by_identifier(host)
    if fixture and fixture.get("baseline"):
        return dict(fixture["baseline"])

    for data in SCENARIOS.values():
        baseline = data.get("baseline", {})
        if baseline.get("event_type") == event_type:
            return dict(baseline)

    return {
        "host": host,
        "event_type": event_type,
        "baseline_normal": False,
        "deviation_score": 0.5,
        "baseline_description": "No local baseline fixture matched this host and event type.",
    }


def _geo_lookup_impl(ip: str) -> dict[str, Any]:
    fixture = _find_by_identifier(ip)
    if fixture:
        geo = fixture.get("geo", {})
        if isinstance(geo, dict) and ip in geo:
            return dict(geo[ip])

    return {
        "ip": ip,
        "country": "US",
        "city": "Unknown",
        "asn": "AS64500",
        "is_vpn_exit": False,
        "is_tor": False,
    }


def _tag_mitre_candidates_impl(alert_type: str, behaviors: list[str]) -> list[str]:
    normalized_behaviors = {str(behavior).lower() for behavior in behaviors}
    candidates: list[str] = []

    if {"authorized_scanner", "known_scanner"} & normalized_behaviors:
        return []
    if {"impossible_travel", "valid_accounts"} & normalized_behaviors:
        candidates.append("T1078")
    if {"lsass_access", "credential_dumping", "credential_access", "rundll32"} & normalized_behaviors:
        candidates.append("T1003.001")
    if "port_scan" in normalized_behaviors or str(alert_type).upper() == "IDS":
        candidates.append("T0846")

    return list(dict.fromkeys(candidates))


def _extract_mitre_candidates(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, dict):
        for key in ("mitre_candidates", "candidates", "techniques"):
            if isinstance(value.get(key), list):
                return [str(item) for item in value[key] if item]
        if value.get("technique"):
            return [str(value["technique"])]
    if isinstance(value, str) and value:
        return [value]
    return []


def _known(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and value.strip().lower() in {"", "unknown", "null", "none", "n/a"}:
        return False
    return True


def _append_open_questions(open_questions: list[str], prefix: str, value: Any) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _append_open_questions(open_questions, path, nested_value)
    elif isinstance(value, list):
        if not value and prefix.endswith("lineage"):
            open_questions.append(f"{prefix} is unavailable")
    elif not _known(value):
        open_questions.append(f"{prefix} is unknown")


def _build_and_post_bundle_impl(all_enrichment: dict[str, Any], alert_id: str) -> dict[str, Any]:
    enrichment = _coerce_dict(all_enrichment)
    fixture = _find_by_alert_id(alert_id)

    raw_alert = (
        enrichment.get("raw_alert")
        or enrichment.get("normalized_alert")
        or enrichment.get("normalize_alert")
        or (fixture or {}).get("raw_alert")
    )
    if not raw_alert:
        raw_alert = _normalize_alert_impl(enrichment.get("raw_payload", enrichment))
    raw_alert = RawAlert.model_validate(raw_alert).model_dump(mode="json")

    asset = (
        enrichment.get("asset")
        or enrichment.get("asset_lookup")
        or enrichment.get("lookup_asset")
        or (fixture or {}).get("asset")
        or _lookup_asset_impl(raw_alert["source_host"])
    )
    baseline = (
        enrichment.get("baseline")
        or enrichment.get("behavioral_baseline")
        or enrichment.get("check_behavioral_baseline")
        or (fixture or {}).get("baseline")
        or _check_behavioral_baseline_impl(raw_alert["source_host"], raw_alert["alert_type"].lower())
    )
    lineage = (
        enrichment.get("lineage")
        or enrichment.get("process_lineage")
        or enrichment.get("get_process_lineage")
        or (fixture or {}).get("lineage")
        or {"lineage": [], "available": False}
    )
    geo = enrichment.get("geo") or enrichment.get("geo_lookup") or (fixture or {}).get("geo") or {}
    mitre_candidates = (
        _extract_mitre_candidates(enrichment.get("mitre_candidates"))
        or _extract_mitre_candidates(enrichment.get("tag_mitre_candidates"))
        or _extract_mitre_candidates((fixture or {}).get("mitre_candidates"))
    )

    existing_ids = set(enrichment.get("existing_evidence_ids") or [])
    generator = EVDGenerator(alert_id)

    def next_evidence_id() -> str:
        evidence_id = generator.next()
        while evidence_id in existing_ids:
            evidence_id = generator.next()
        existing_ids.add(evidence_id)
        return evidence_id

    evidence: list[dict[str, Any]] = []
    seen_facts: set[str] = set()

    def add_fact(fact: str, source_type: str, confidence: float, raw_ref: str | None = None) -> None:
        normalized_fact = " ".join(str(fact).split())
        if not normalized_fact or normalized_fact in seen_facts:
            return
        seen_facts.add(normalized_fact)
        evidence.append(
            {
                "evidence_id": next_evidence_id(),
                "fact": normalized_fact,
                "source_type": source_type,
                "confidence": confidence,
                "raw_ref": raw_ref,
            }
        )

    raw_payload = raw_alert["raw_payload"]
    add_fact(
        f"Alert {raw_alert['id']} fired as {raw_alert['alert_type']} on source {raw_alert['source_host']} at {raw_alert['timestamp']}.",
        "raw_log",
        0.99,
        "raw_alert",
    )
    if raw_payload.get("rule_name"):
        add_fact(f"Detection rule was {raw_payload['rule_name']}.", "raw_log", 0.98, "raw_payload.rule_name")
    if raw_alert["alert_type"] == "IDS":
        add_fact(
            f"Network activity originated from {raw_payload.get('src_ip')} toward {raw_payload.get('dst_ip')} using scan type {raw_payload.get('scan_type')}.",
            "raw_log",
            0.97,
            "raw_payload.src_ip",
        )
        if raw_payload.get("ports_scanned"):
            add_fact(f"Ports scanned were {raw_payload['ports_scanned']}.", "raw_log", 0.96, "raw_payload.ports_scanned")
    if raw_alert["alert_type"] == "AUTH":
        login_1 = raw_payload.get("login_1", {})
        login_2 = raw_payload.get("login_2", {})
        add_fact(
            f"User {raw_payload.get('user')} authenticated from {login_1.get('ip')} and {login_2.get('ip')} within {raw_payload.get('travel_time_minutes')} minutes.",
            "raw_log",
            0.98,
            "raw_payload.login_1",
        )
        add_fact(
            f"Second login device was {login_2.get('device')} with MFA={login_2.get('mfa')}.",
            "raw_log",
            0.95,
            "raw_payload.login_2",
        )
    if raw_alert["alert_type"] == "EDR":
        add_fact(
            f"Process {raw_payload.get('process')} pid {raw_payload.get('pid')} accessed target process {raw_payload.get('target_process')} with rights {raw_payload.get('access_rights')}.",
            "raw_log",
            0.99,
            "raw_payload.process",
        )
        add_fact(f"Observed command line: {raw_payload.get('command_line')}.", "raw_log", 0.97, "raw_payload.command_line")

    add_fact(
        f"CMDB maps {asset.get('hostname')} to owner {asset.get('owner_team')} in {asset.get('environment')} with criticality {asset.get('criticality_tier')}.",
        "cmdb",
        0.9,
        "cmdb.asset",
    )
    add_fact(f"CMDB known scanner flag is {asset.get('is_known_scanner')}.", "cmdb", 0.9, "cmdb.is_known_scanner")

    add_fact(
        f"Behavioral baseline normal={baseline.get('baseline_normal')} with deviation score {baseline.get('deviation_score')}: {baseline.get('baseline_description')}",
        "baseline",
        0.86,
        "baseline",
    )

    if isinstance(geo, list):
        geo_records = geo
    elif isinstance(geo, dict) and "ip" in geo:
        geo_records = [geo]
    elif isinstance(geo, dict):
        geo_records = [record for record in geo.values() if isinstance(record, dict)]
    else:
        geo_records = []

    for record in geo_records:
        add_fact(
            f"GeoIP maps {record.get('ip')} to {record.get('city')}, {record.get('country')} on {record.get('asn')} with vpn_exit={record.get('is_vpn_exit')} and tor={record.get('is_tor')}.",
            "geo",
            0.8,
            f"geo.{record.get('ip')}",
        )

    lineage_records = lineage.get("lineage", []) if isinstance(lineage, dict) else []
    if lineage_records:
        chain = " -> ".join(f"{item.get('name')}({item.get('pid')})" for item in lineage_records)
        add_fact(f"Process lineage is {chain}.", "lineage", 0.88, "lineage")
        for item in lineage_records:
            add_fact(
                f"Process {item.get('name')} pid {item.get('pid')} ran command line {item.get('cmdline')} with parent {item.get('parent_name')} pid {item.get('parent_pid')}.",
                "lineage",
                0.86,
                f"lineage.{item.get('pid')}",
            )

    for technique in mitre_candidates:
        add_fact(f"Candidate MITRE ATT&CK technique is {technique}.", "mitre", 0.78, "mitre_candidates")

    open_questions: list[str] = []
    _append_open_questions(open_questions, "raw_alert", raw_alert)
    _append_open_questions(open_questions, "asset", asset)
    _append_open_questions(open_questions, "baseline", baseline)
    if raw_alert["alert_type"] == "AUTH" and not geo_records:
        open_questions.append("geo enrichment is unavailable for auth login IPs")
    if raw_alert["alert_type"] == "EDR" and not lineage_records:
        open_questions.append("process lineage is unavailable for EDR alert")

    criticality = str(asset.get("criticality_tier") or "low").lower()
    if criticality not in {"critical", "high", "medium", "low"}:
        open_questions.append("asset.criticality_tier is not one of critical/high/medium/low")
        criticality = "low"

    bundle_payload = {
        "bundle_id": f"BND-{generator.prefix}",
        "alert_id": alert_id,
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC),
        "alert_type": raw_alert["alert_type"],
        "asset_criticality": criticality,
        "evidence": evidence,
        "mitre_candidates": mitre_candidates,
        "open_questions": list(dict.fromkeys(open_questions)),
    }

    try:
        bundle = EvidenceBundle.model_validate(bundle_payload)
    except Exception as exc:
        raise ValueError(f"EvidenceBundle validation failed: {exc}") from exc

    return bundle.model_dump(mode="json")


@tool
def normalize_alert(raw_payload: dict) -> dict:
    """Normalize a raw EDR, IDS, or AUTH alert payload into the RawAlert schema."""

    return _normalize_alert_impl(raw_payload)


@tool
def lookup_asset(identifier: str) -> dict:
    """Look up mock CMDB data for a hostname, IP address, username, or alert ID."""

    return _lookup_asset_impl(identifier)


@tool
def get_process_lineage(pid: int | None = None, host: str = "") -> dict:
    """Return mock EDR parent-child process lineage for a host and process ID."""

    return _get_process_lineage_impl(pid=pid, host=host)


@tool
def check_behavioral_baseline(host: str, event_type: str) -> dict:
    """Compare an event against mock historical baseline behavior for the host."""

    return _check_behavioral_baseline_impl(host=host, event_type=event_type)


@tool
def geo_lookup(ip: str) -> dict:
    """Return mock GeoIP, ASN, VPN, and Tor enrichment for an IP address."""

    return _geo_lookup_impl(ip)


@tool
def tag_mitre_candidates(alert_type: str, behaviors: list[str]) -> list[str]:
    """Map observed alert behaviors to candidate MITRE ATT&CK technique IDs."""

    return _tag_mitre_candidates_impl(alert_type=alert_type, behaviors=behaviors)


@tool
def build_and_post_bundle(all_enrichment: dict, alert_id: str) -> dict:
    """Compile enrichment output into a validated EvidenceBundle with deterministic EVD IDs."""

    return _build_and_post_bundle_impl(all_enrichment=all_enrichment, alert_id=alert_id)


TRIAGE_TOOLS = [
    normalize_alert,
    lookup_asset,
    get_process_lineage,
    check_behavioral_baseline,
    geo_lookup,
    tag_mitre_candidates,
    build_and_post_bundle,
]
