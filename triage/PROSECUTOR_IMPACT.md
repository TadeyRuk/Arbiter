# Prosecutor Impact From Triage Changes

## What Changed In Triage

Triage now posts structured evidence bundles in Band.

The main marker is:

```text
EVIDENCE_BUNDLE_READY
{bundle JSON}
```

The bundle contains the only evidence Prosecutor is allowed to cite.

Important fields:

- `bundle_id`
- `alert_id`
- `asset_criticality`
- `evidence[].evidence_id`
- `evidence[].fact`
- `mitre_candidates`
- `open_questions`

## What Prosecutor Should Do

Prosecutor should argue real incident only from Triage evidence.

Rules:

- Every claim must cite at least one valid `EVD-*` ID.
- Do not invent enrichment, process lineage, asset criticality, or MITRE mappings.
- Use `mitre_candidates` when present.
- Concede if the evidence supports a benign explanation.
- If a decisive fact is missing, ask Judge to request clarification from Triage.

## Best Prosecutor Demo Case

Use:

```text
DEMO-LSASS-001
```

Triage emits:

```text
BND-900ccf
EVD-900ccf-001 through EVD-900ccf-012
```

Strong Prosecutor evidence:

- `EVD-900ccf-003`: `rundll32.exe` accessed `lsass.exe`.
- `EVD-900ccf-004`: suspicious command line from `C:\Windows\Temp\srv.dll,#1`.
- `EVD-900ccf-005`: affected host is a critical finance asset.
- `EVD-900ccf-007`: behavior is not normal for the host.
- `EVD-900ccf-008`: process lineage shows `cmd.exe -> rundll32.exe -> lsass.exe`.
- `EVD-900ccf-012`: MITRE `T1003.001`.

Expected Prosecutor position:

```text
Likely real incident / credential dumping behavior.
```

## Suggested Prosecutor Output

```json
{
  "position": "real_incident",
  "claims": [
    {
      "claim": "The alert shows likely LSASS credential dumping behavior.",
      "evidence_ids": ["EVD-900ccf-003", "EVD-900ccf-012"]
    },
    {
      "claim": "The behavior is more severe because it occurred on a critical finance asset.",
      "evidence_ids": ["EVD-900ccf-005"]
    }
  ],
  "confidence": 0.9,
  "recommended_action": "escalate_human"
}
```

## Quick Catch-Up For The Prosecutor Owner

Wait for Triage to post `EVIDENCE_BUNDLE_READY`, parse the bundle JSON, and argue from the listed EVD IDs. The LSASS case is the strongest one for Prosecutor.
