# Orchestrator Impact From Triage Changes

## What Changed In Triage

Triage is now ready to be the first substantive step in the Band room.

It supports three demo triggers:

```text
@Arbiter | TRIAGE DEMO-SCAN-001
@Arbiter | TRIAGE DEMO-TRAVEL-001
@Arbiter | TRIAGE DEMO-LSASS-001
```

For each trigger, Triage posts:

```text
EVIDENCE_BUNDLE_READY
{bundle JSON}
```

Triage also handles Judge clarification requests and posts:

```text
TRIAGE_SUPPLEMENT
{supplement JSON}
```

## What Orchestrator Should Do

Orchestrator should enforce the room sequence:

1. Send or route the alert to Triage.
2. Wait for `EVIDENCE_BUNDLE_READY`.
3. Notify Prosecutor and Defender that the bundle is ready.
4. Wait for both arguments.
5. Ask Judge to validate citations and issue a disposition.
6. If Judge requests clarification, route the request back to Triage.
7. Wait for `TRIAGE_SUPPLEMENT`, then resume Judge evaluation.

## Important Dependency

Do not trigger Prosecutor or Defender before Triage posts the bundle.

Their arguments depend on:

```text
evidence[].evidence_id
```

Without those IDs, Judge cannot validate citations.

## Suggested Demo Flow

Use this order for presentation:

1. `DEMO-SCAN-001`: Defender clears likely false positive.
2. `DEMO-LSASS-001`: Prosecutor argues likely real incident.
3. `DEMO-TRAVEL-001`: Judge asks Triage for clarification and receives a supplement.

## Current Tested Bundle IDs

- `DEMO-SCAN-001` -> `BND-1c7b09`
- `DEMO-TRAVEL-001` -> `BND-443645`
- `DEMO-LSASS-001` -> `BND-900ccf`

## Quick Catch-Up For The Orchestrator Owner

Make the Orchestrator wait for the literal `EVIDENCE_BUNDLE_READY` marker before advancing the workflow. Then pass the bundle context to Prosecutor, Defender, and Judge in the same Band room.
