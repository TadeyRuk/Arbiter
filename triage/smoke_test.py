"""Local smoke checks for the ARBITER Triage evidence subsystem."""

from __future__ import annotations

import json

from tools import (
    SCENARIOS,
    _build_and_post_bundle_impl,
    _check_behavioral_baseline_impl,
    _geo_lookup_impl,
    _get_process_lineage_impl,
    _lookup_asset_impl,
    _normalize_alert_impl,
    _tag_mitre_candidates_impl,
)


DEMO_ALERT_IDS = ("DEMO-SCAN-001", "DEMO-TRAVEL-001", "DEMO-LSASS-001")


def build_enrichment(alert_id: str) -> dict:
    scenario = SCENARIOS[alert_id]
    raw_alert = _normalize_alert_impl(scenario)
    raw_payload = raw_alert["raw_payload"]
    asset = _lookup_asset_impl(raw_alert["source_host"])
    event_type = scenario.get("baseline", {}).get("event_type", raw_alert["alert_type"].lower())
    baseline = _check_behavioral_baseline_impl(asset["hostname"], event_type)
    lineage = _get_process_lineage_impl(raw_payload.get("pid"), raw_alert["source_host"])

    geo_records = {}
    for login_key in ("login_1", "login_2"):
        login = raw_payload.get(login_key)
        if isinstance(login, dict) and login.get("ip"):
            geo_records[login["ip"]] = _geo_lookup_impl(login["ip"])

    behaviors = scenario.get("behaviors", [])
    mitre_candidates = _tag_mitre_candidates_impl(raw_alert["alert_type"], behaviors)

    return {
        "raw_alert": raw_alert,
        "asset": asset,
        "baseline": baseline,
        "lineage": lineage,
        "geo": geo_records or scenario.get("geo", {}),
        "mitre_candidates": mitre_candidates,
    }


def main() -> None:
    for alert_id in DEMO_ALERT_IDS:
        enrichment = build_enrichment(alert_id)
        first = _build_and_post_bundle_impl(enrichment, alert_id)
        second = _build_and_post_bundle_impl(enrichment, alert_id)

        first_ids = [item["evidence_id"] for item in first["evidence"]]
        second_ids = [item["evidence_id"] for item in second["evidence"]]
        if first_ids != second_ids:
            raise AssertionError(f"EVD ID sequence changed between runs for {alert_id}")
        if not first["evidence"]:
            raise AssertionError(f"No evidence generated for {alert_id}")

        print(
            json.dumps(
                {
                    "alert_id": alert_id,
                    "bundle_id": first["bundle_id"],
                    "evidence_count": len(first["evidence"]),
                    "first_evd_id": first_ids[0],
                    "last_evd_id": first_ids[-1],
                    "mitre_candidates": first["mitre_candidates"],
                    "open_questions": first["open_questions"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
