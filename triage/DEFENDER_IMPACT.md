# Defender Impact From Triage Changes

## What Changed In Triage

Triage now posts structured evidence bundles directly in the Band room.

The main message format is:

```text
EVIDENCE_BUNDLE_READY
{bundle JSON}
```

Each evidence fact has a stable `EVD-*` ID. Defender should only cite those IDs.

Triage also supports supplements:

```text
TRIAGE_SUPPLEMENT
{supplement JSON}
```

Supplements add new evidence IDs. They do not replace or mutate old evidence.

## What Defender Should Do

Defender should treat the Triage bundle as the source of truth.

When arguing false positive:

- Cite only IDs from `evidence[].evidence_id`.
- Do not invent benign explanations.
- Look for known scanner flags, normal baselines, service accounts, VPN context, or expected maintenance behavior.
- If the evidence is not enough to clear the alert, say that clearly.
- If a missing fact would decide the case, ask Judge to request re-triage from Triage.

## Best Defender Demo Case

Use:

```text
DEMO-SCAN-001
```

Triage emits:

```text
BND-1c7b09
EVD-1c7b09-001 through EVD-1c7b09-007
```

Important evidence:

- `EVD-1c7b09-005`: CMDB maps the scanner host to Security Engineering.
- `EVD-1c7b09-006`: CMDB known scanner flag is true.
- `EVD-1c7b09-007`: behavioral baseline says this scan is normal and scheduled.
- `mitre_candidates` is empty.

Expected Defender position:

```text
Likely false positive / authorized scanner activity.
```

## Suggested Defender Output

```json
{
  "position": "false_positive",
  "claims": [
    {
      "claim": "The source appears to be an authorized internal scanner.",
      "evidence_ids": ["EVD-1c7b09-005", "EVD-1c7b09-006"]
    },
    {
      "claim": "The behavior matches a normal scheduled scan baseline.",
      "evidence_ids": ["EVD-1c7b09-007"]
    }
  ],
  "confidence": 0.85,
  "open_questions": []
}
```

## Quick Catch-Up For The Defender Owner

Run the Defender agent in the same Band room after Triage posts the bundle. Build the argument from the EVD IDs above. Do not cite raw logs directly unless they are represented by an EVD ID.
