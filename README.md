# Arbiter

A multi-agent system that triages security alerts by having AI agents argue both sides of a case from evidence, then reach a defensible, auditable verdict.

When an alert fires, six agents work together inside a shared Band room:

| Agent | Role |
|-------|------|
| **Orchestrator** | Coordinates the workflow. Routes the alert through each stage. |
| **Triage** | Enriches the alert and builds the evidence bundle. Only agent allowed to introduce evidence. |
| **Prosecutor** | Argues the alert is a real incident, citing evidence. |
| **Defender** | Argues the alert is a false positive, citing evidence. |
| **Judge** | Validates citations, scores severity, issues a verdict. Escalates to a human when needed. |
| **System Diagnostics Agent** | Forwards WARNING-and-above terminal logs (including tracebacks) into the Band chat so failures are visible when the platform does not surface them. |

The result is not just a classification — it's a reasoned, citation-backed decision fit for a SOC 2 review or breach post-mortem.

---

## System Diagnostics Agent

When an Arbiter agent fails, Band often shows nothing useful in chat — the traceback stays in your terminal. The **System Diagnostics Agent** mirrors that output into the shared room so the whole team can see what went wrong.

### What it posts

| Source | Examples |
|--------|----------|
| **ERROR / CRITICAL** | LLM API failures, uncaught exceptions, full tracebacks |
| **WARNING** | Missing agents in room, websocket reconnect loops, orchestrator escalations |
| **Structured agent errors** | `[AGENT_ERROR] prosecutor: PermissionDeniedError: ...` from Orchestrator, Prosecutor, Defender |

Diagnostics messages are prefixed with `[SYSTEM_DIAGNOSTICS]` so the Orchestrator does not treat them as debate arguments.

### What you need

- **Band credentials only** — no Featherless API key, no LLM
- A separate Remote Agent registered on [app.band.ai](https://app.band.ai) named **System Diagnostics Agent** (or `Arbiter | System Diagnostics`)
- The agent added to the same adjudication room as the other Arbiter agents

### Setup

1. On Band, create a **Remote Agent** and copy the ID + API key.
2. Copy the example config and paste your Band credentials:

```bash
cp diagnostics/agent_config.yaml.example diagnostics/agent_config.yaml
```

Then edit `diagnostics/agent_config.yaml`:

```yaml
diagnostics_agent:
  agent_id: your-band-agent-id
  api_key: your-band-api-key
```

3. Install dependencies:

```bash
pip3 install -r diagnostics/requirements.txt
```

4. Ensure Band URLs are in your root `.env` (same as other agents):

```
THENVOI_REST_URL=https://app.band.ai/
THENVOI_WS_URL=wss://app.band.ai/api/v1/socket/websocket
```

5. Add **System Diagnostics Agent** to your Band room via **Participants +**.

### Running

**All agents together** (recommended — one process, shared log bridge):

```bash
python3 run_all.py
```

`run_all.py` calls `install_diagnostics_logging()` at startup and starts the diagnostics agent alongside Orchestrator, Triage, Prosecutor, Defender, and Judge.

**Diagnostics only** (standalone):

```bash
python3 diagnostics/agent.py
```

> Run diagnostics in the **same process** as the other agents (`run_all.py`) so terminal logs from all agents reach the bridge. A standalone diagnostics process only sees logs from its own Python process.

### Chat commands

Mention the agent or send:

- `recent` — last buffered diagnostic entries
- `status` — same as `recent`

### When agents look unresponsive

1. Check **System Diagnostics Agent** posts in the room for tracebacks.
2. Check the terminal running `run_all.py` or `agent.py`.
3. Common causes: invalid Featherless API key, Featherless plan without API access (`403 upgrade_required`), or a missing agent handle in the room.

The Orchestrator also posts `[AGENT_ERROR]` summaries when Prosecutor, Defender, or itself fail during a case, and halts the workflow instead of waiting forever during debate.

---

## Setup

Each teammate runs one agent. Follow the guide for your OS:

- [macOS setup](SETUP_MACOS.md)
- [Windows setup](SETUP_WINDOWS.md)

---

## Getting your API keys

Before running an agent you need a **Band agent token** (covered in the OS setup guides). Most agents also need a **Featherless API key** for the LLM — **System Diagnostics Agent does not**.

### Featherless API key

Featherless is the inference provider for the open-source models used by the Orchestrator and Defender agents.

1. Go to [featherless.ai](https://featherless.ai) and click **Sign up**
2. Create a free account (no credit card required to start)
3. Once logged in, go to **Account → API Keys**: [featherless.ai/account/api-keys](https://featherless.ai/account/api-keys)
4. Click **Create new key**, give it a name (e.g. `arbiter`), and copy it

### Configure your `.env`

In the project root, copy the example file and fill in your key:

```bash
cp .env.example .env
```

Then open `.env` and replace the placeholder:

```
FEATHERLESS_API_KEY=your_key_here
THENVOI_REST_URL=https://app.band.ai/
THENVOI_WS_URL=wss://app.band.ai/api/v1/socket/websocket
```

> **Note:** The `THENVOI_*` URLs are already correct — don't change them.

> **Never commit `.env`** — it contains your private API key.

---

## Project structure

```
Arbiter/
├── orchestrator/       Orchestrator agent (Band SDK + Featherless)
├── triage/             Triage agent (LangChain + Claude Haiku)
├── prosecutor/         Prosecutor agent (CrewAI + Claude Sonnet)
├── defender/           Defender agent (LangChain + Featherless)
├── judge/              Judge agent (Band SDK + GPT-4o)
├── diagnostics/        System Diagnostics Agent (Band only — mirrors terminal errors to chat)
├── shared/             Shared data models (Alert, Evidence, Disposition) + diagnostics bridge
└── demo/               Sample alerts for testing
```

---

## Tech stack

- **Coordination** — [Band](https://band.ai) (shared adjudication room)
- **Frameworks** — LangChain, CrewAI, Band SDK
- **Models** — Claude Haiku, Claude Sonnet, Qwen3-32B (Featherless), GPT-4o
- **Demo data** — authorized port scan, impossible travel login, LSASS credential dump
