"""
Live smoke test — runs the Defender core against the real Featherless model
on the three demo bundles. No Band room required; it calls the LLM directly.

Needs FEATHERLESS_API_KEY in Arbiter/.env. Run from the repo root:

    python defender/smoke_live.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from defender.defense import build_defense  # noqa: E402
from defender.fixtures import ALL_BUNDLES  # noqa: E402

EXPECTED = {
    "authorized_scanner": "cleared (benign)",
    "impossible_travel": "either (ambiguous)",
    "lsass_dump": "not cleared (malicious)",
}


def main() -> int:
    load_dotenv(_REPO_ROOT / ".env")
    api_key = os.getenv("FEATHERLESS_API_KEY_DEFENDER") or os.getenv("FEATHERLESS_API_KEY")
    if not api_key:
        print("Neither FEATHERLESS_API_KEY_DEFENDER nor FEATHERLESS_API_KEY set in Arbiter/.env — cannot run live smoke.")
        return 2

    model = (
        os.getenv("FEATHERLESS_MODEL_DEFENDER")
        or os.getenv("FEATHERLESS_MODEL")
        or "Qwen/Qwen3-0.6B"
    )
    llm = ChatOpenAI(
        model=model,
        base_url="https://api.featherless.ai/v1",
        api_key=api_key,
        temperature=0,
    )

    for name, build in ALL_BUNDLES.items():
        bundle = build()
        result = build_defense(bundle, llm)
        status = "CLEARED" if result.cleared else "NOT cleared"
        print(f"\n=== {bundle.alert.alert_id} {name} ===")
        print(f"expected: {EXPECTED[name]}   ->   defender: {status}")
        for claim in result.claims:
            print(f"  + {claim.evidence_ids}  {claim.argument}")
        for struck in result.struck:
            print(f"  x STRUCK (bad cite): {struck}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
