"""
Offline tests for the Defender core. No network, no API key.

A FakeLLM returns canned JSON so we can assert the validation behaviour that
the live model cannot guarantee: citations are checked against the bundle,
hallucinated IDs are stripped, empty claims are struck, and thin context
produces no claims.

Run from the repo root:  pytest defender/test_defense.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from defender import defense  # noqa: E402
from defender.defense import build_defense  # noqa: E402
from defender.fixtures import (  # noqa: E402
    authorized_scanner_bundle,
    impossible_travel_bundle,
    lsass_dump_bundle,
)


class FakeLLM:
    """Returns a fixed string, mimicking a LangChain chat model's .invoke."""

    def __init__(self, content: str):
        self._content = content
        self.calls: list = []

    def invoke(self, messages):
        self.calls.append(messages)

        class _Msg:
            content = self._content

        return _Msg()


# --- fixtures sanity -------------------------------------------------------

def test_fixtures_have_unique_stable_ids():
    for build in (authorized_scanner_bundle, impossible_travel_bundle, lsass_dump_bundle):
        bundle = build()
        ids = [e.evidence_id for e in bundle.items]
        assert ids, "bundle has no evidence"
        assert len(ids) == len(set(ids)), f"duplicate evidence_id in {bundle.alert.alert_id}"


# --- citation validation ---------------------------------------------------

def test_hallucinated_id_is_stripped_but_claim_kept():
    bundle = authorized_scanner_bundle()
    llm = FakeLLM(
        '{"claims": [{"evidence_ids": ["EVD-1", "EVD-99"], '
        '"argument": "Registered scanner in its window.", "mitre_technique": null}]}'
    )
    result = build_defense(bundle, llm)
    assert len(result.claims) == 1
    assert result.claims[0].evidence_ids == ["EVD-1"]  # EVD-99 dropped
    assert result.struck == []
    assert result.cleared


def test_claim_with_only_fake_ids_is_struck():
    bundle = authorized_scanner_bundle()
    llm = FakeLLM(
        '{"claims": [{"evidence_ids": ["EVD-404"], '
        '"argument": "Totally made up.", "mitre_technique": null}]}'
    )
    result = build_defense(bundle, llm)
    assert result.claims == []
    assert result.struck == ["Totally made up."]
    assert not result.cleared


def test_thin_context_produces_no_claims():
    bundle = lsass_dump_bundle()
    llm = FakeLLM('{"claims": []}')
    result = build_defense(bundle, llm)
    assert result.claims == []
    assert not result.cleared


def test_markdown_fenced_json_is_parsed():
    bundle = impossible_travel_bundle()
    fenced = (
        "```json\n"
        '{"claims": [{"evidence_ids": ["EVD-1"], '
        '"argument": "login_2 came from the corp VPN range.", "mitre_technique": null}]}\n'
        "```"
    )
    result = build_defense(bundle, FakeLLM(fenced))
    assert len(result.claims) == 1
    assert result.claims[0].evidence_ids == ["EVD-1"]


def test_malformed_json_is_handled_gracefully():
    bundle = authorized_scanner_bundle()
    result = build_defense(bundle, FakeLLM("the model rambled and forgot to emit json"))
    assert result.claims == []
    assert result.struck == []
    assert not result.cleared


def test_claim_missing_argument_is_ignored():
    bundle = authorized_scanner_bundle()
    llm = FakeLLM('{"claims": [{"evidence_ids": ["EVD-1"], "argument": ""}]}')
    result = build_defense(bundle, llm)
    assert result.claims == []
    assert result.struck == []


def test_prompt_includes_bundle_payload():
    bundle = authorized_scanner_bundle()
    msgs = defense.build_prompt(bundle)
    assert msgs[0]["role"] == "system"
    assert "Defender" in msgs[0]["content"]
    assert "EVD-1" in msgs[1]["content"]
