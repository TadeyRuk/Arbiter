# Judge Impact From Triage Changes

## What Changed In Triage

Triage now creates the adjudication evidence contract.

It posts:

```text
EVIDENCE_BUNDLE_READY
{bundle JSON}
```

and, when asked for more context:

```text
TRIAGE_SUPPLEMENT
{supplement JSON}
```

Evidence IDs are deterministic and stable. Judge should validate all Prosecutor and Defender citations against those IDs.

## What Judge Should Do

Judge should build a valid citation set from:

```text
EvidenceBundle.evidence[].evidence_id
TRIAGE_SUPPLEMENT.evidence[].evidence_id
```

Then:

- Strike claims that cite missing or fake evidence IDs.
- Ignore unsupported claims when forming the verdict.
- Ask Triage for clarification if a decisive fact is missing.
- Only request re-triage once per decisive missing question.
- Score severity after citation validation.

## Re-Triage Request Format

Band requires a mention. Send requests like:

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

Expected Triage response:

```text
TRIAGE_SUPPLEMENT
{new evidence JSON}
```

## Best Judge Demo Case

Use:

```text
DEMO-TRAVEL-001
```

Triage emits:

```text
BND-443645
EVD-443645-001 through EVD-443645-010
```

Good re-triage question:

```text
Are either login IPs VPN or Tor exits?
```

This shows Judge can send the case back to Triage when missing context affects the decision.

## Suggested Judge Output

```json
{
  "verdict": "needs_more_evidence",
  "confidence": 0.72,
  "requires_human_approval": false,
  "struck_claims": [
    {
      "claim": "Example unsupported claim",
      "reason": "Cited evidence ID is not present in the bundle."
    }
  ],
  "next_action": {
    "type": "JUDGE_REQUESTS_CLARIFICATION",
    "questions": ["Are either login IPs VPN or Tor exits?"]
  }
}
```

## Quick Catch-Up For The Judge Owner

Update Judge to parse `EVIDENCE_BUNDLE_READY` and `TRIAGE_SUPPLEMENT` messages. The main job is citation validation: if an argument cites an ID not in the bundle or supplement, strike it.
