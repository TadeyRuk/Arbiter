# Arbiter

A multi-agent system that triages security alerts by having AI agents argue both sides of a case from evidence, then reach a defensible, auditable verdict.

When an alert fires, five agents work together inside a shared Band room:

| Agent | Role |
|-------|------|
| **Orchestrator** | Coordinates the workflow. Routes the alert through each stage. |
| **Triage** | Enriches the alert and builds the evidence bundle. Only agent allowed to introduce evidence. |
| **Prosecutor** | Argues the alert is a real incident, citing evidence. |
| **Defender** | Argues the alert is a false positive, citing evidence. |
| **Judge** | Validates citations, scores severity, issues a verdict. Escalates to a human when needed. |

The result is not just a classification — it's a reasoned, citation-backed decision fit for a SOC 2 review or breach post-mortem.

---

## Setup

Each teammate runs one agent. Follow the guide for your OS:

- [macOS setup](SETUP_MACOS.md)
- [Windows setup](SETUP_WINDOWS.md)

---

## Project structure

```
Arbiter/
├── orchestrator/       Orchestrator agent (Band SDK + Featherless)
├── triage/             Triage agent (LangChain + Claude Haiku)
├── prosecutor/         Prosecutor agent (CrewAI + Claude Sonnet)
├── defender/           Defender agent (LangChain + Featherless)
├── judge/              Judge agent (Band SDK + GPT-4o)
├── shared/             Shared data models (Alert, Evidence, Disposition)
└── demo/               Sample alerts for testing
```

---

## Tech stack

- **Coordination** — [Band](https://band.ai) (shared adjudication room)
- **Frameworks** — LangChain, CrewAI, Band SDK
- **Models** — Claude Haiku, Claude Sonnet, Qwen3-32B (Featherless), GPT-4o
- **Demo data** — authorized port scan, impossible travel login, LSASS credential dump
