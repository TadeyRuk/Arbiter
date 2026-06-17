# Triage Agent Notes

## Current Status

Triage is working end to end in Band for the demo scenarios.

It responds visibly in the Band room with:

```text
EVIDENCE_BUNDLE_READY
{bundle JSON}
```

It also supports Judge clarification requests and responds with:

```text
TRIAGE_SUPPLEMENT
{supplement JSON}
```

## Role

Triage is the only agent allowed to introduce evidence into the room. It normalizes alerts, enriches them with mock CMDB/baseline/GeoIP/process-lineage data, assigns stable evidence IDs, and posts a structured bundle for the other agents.

Other agents should treat the Triage bundle as the source of truth.

## Tested Demo Inputs

Send these in Band:

```text
@Arbiter | TRIAGE DEMO-SCAN-001
@Arbiter | TRIAGE DEMO-TRAVEL-001
@Arbiter | TRIAGE DEMO-LSASS-001
```

Expected bundles:

- `DEMO-SCAN-001` -> `BND-1c7b09`, `EVD-1c7b09-001` through `EVD-1c7b09-007`
- `DEMO-TRAVEL-001` -> `BND-443645`, `EVD-443645-001` through `EVD-443645-010`
- `DEMO-LSASS-001` -> `BND-900ccf`, `EVD-900ccf-001` through `EVD-900ccf-012`

## Re-Triage Request Format

Band requires a mention, so send Judge requests like this:

```text
@Arbiter | TRIAGE
{
  "type": "JUDGE_REQUESTS_CLARIFICATION",
  "original_bundle_id": "BND-443645",
  "requested_by": "judge",
  "questions": ["Are either login IPs VPN or Tor exits?"],
  "contested_evd_ids": ["EVD-443645-008", "EVD-443645-009"]
}
```

Expected response:

```text
TRIAGE_SUPPLEMENT
{new evidence JSON}
```

## Integration Contract

- Triage owns evidence creation.
- EVD IDs are deterministic and should not be changed by other agents.
- Supplements add new EVD IDs; they do not mutate old evidence.
- If context is missing, Judge should request clarification instead of guessing.

## Local Smoke Test

```bash
triage/.venv/bin/python triage/smoke_test.py
```
