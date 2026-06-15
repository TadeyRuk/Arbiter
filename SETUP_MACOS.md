# Arbiter — Setup Guide (macOS)

## What you're setting up
You're connecting your AI agent to a shared adjudication system. Once running, your agent lives on Band and responds automatically when a security alert comes in.

---

## Step 1 — Get the code

```bash
git clone https://github.com/TadeyRuk/Arbiter.git
cd Arbiter
```

---

## Step 2 — Create your agent on Band

Go to [app.band.ai](https://app.band.ai), sign in, then click **Agents** in the left sidebar.

![Agents tab](docs/screenshots/agents-tab.png)

Click **New Agent** → **Remote Agent**. Fill in your agent name and description.

> Name it `Arbiter | AGENT_NAME` — replace `AGENT_NAME` with your role (Triage, Prosecutor, Defender, or Judge).

![Agent info form](docs/screenshots/agent-info.png)

Scroll down and click **Connect Remote Agent**.

![Connect Remote Agent button](docs/screenshots/finish-remote-agent.png)

A popup will show your **ID** and **API Key**. Copy both — the API Key is only shown once.

![Agent keys popup](docs/screenshots/agent-keys.png)

---

## Step 3 — Go to your agent folder

Open the project in your editor. Find your folder:

| You are | Your folder |
|---------|-------------|
| Triage | `triage/` |
| Prosecutor | `prosecutor/` |
| Defender | `defender/` |
| Judge | `judge/` |

![Pick your agent folder](docs/screenshots/pick-agent.png)

Open `agent_config.yaml` inside your folder and paste in the ID and API Key you copied.

![Fill in agent_config.yaml](docs/screenshots/config-yaml.png)

---

## Step 4 — Set your API key

In your terminal, go to your agent folder and create a `.env` file:

```bash
cd triage    # replace with your folder
cp ../.env.example .env
```

Open `.env` and fill in your LLM API key:

| Your folder | Key to fill in | Where to get it |
|-------------|----------------|-----------------|
| `triage/` | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key |
| `prosecutor/` | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) → API Keys → Create Key |
| `defender/` | `FEATHERLESS_API_KEY` | [featherless.ai/account/api-keys](https://featherless.ai/account/api-keys) |
| `judge/` | `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → Create new secret key |

The Band URLs are already pre-filled — don't change them.

---

## Step 5 — Install dependencies

```bash
pip3 install -r requirements.txt
```

---

## Step 6 — Run your agent

```bash
python3 agent.py
```

You should see:
```
INFO:band.agent:Agent started: <Your Agent Name>
```

Keep this terminal open — closing it stops your agent.

---

## Step 7 — Add your agent to a Band room

Go back to Band. Open or create a room. Click **Participants +** in the top right.

![Participants panel](docs/screenshots/participants.png)

Search for your agent by name and select it, then click **Done**.

![Select your agent](docs/screenshots/register-agent.png)

Your agent is now in the room. Mention it with `@` to send it a message.

![Agent live in room](docs/screenshots/finished.png)

---

## Troubleshooting

**Agent doesn't respond** — make sure `python3 agent.py` is still running in your terminal.

**`ModuleNotFoundError`** — run `pip3 install -r requirements.txt` again.

**API key error** — check the key in `.env` has no extra spaces or quotes.

---

> **Never commit** `agent_config.yaml` or `.env` — they contain your private keys.
