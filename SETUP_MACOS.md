# Arbiter — Setup Guide (macOS)

## What you're setting up
You're connecting your AI agent to a shared adjudication system. Once running, your agent lives on Band and responds automatically when a security alert comes in.

---

## Step 1 — Get the code

```bash
git clone <repo-url>
cd Arbiter
```

---

## Step 2 — Go to your agent folder

Each person owns one folder. Find yours:

| You are | Your folder |
|---------|-------------|
| Triage | `triage/` |
| Prosecutor | `prosecutor/` |
| Defender | `defender/` |
| Judge | `judge/` |

```bash
cd triage    # replace with your folder
```

---

## Step 3 — Create your agent on Band

1. Go to [app.band.ai](https://app.band.ai) and sign in
2. Click **Agents** → **New Agent** → **Remote Agent**
3. Give it a name (e.g. `Triage Agent`)
4. Copy the **Agent UUID** and **API Key** shown after creation

---

## Step 4 — Add your credentials

Copy the config template and fill it in:

```bash
cp agent_config.yaml agent_config.yaml.bak  # already a template, just edit it
```

Open `agent_config.yaml` and replace the placeholder values:

```yaml
triage_agent:             # use your role name (triage/prosecutor/defender/judge)
  agent_id: "paste-your-uuid-here"
  api_key: "paste-your-api-key-here"
```

Then create your `.env` file:

```bash
cp ../.env.example .env
```

Open `.env` and fill in your LLM API key:

| Your folder | Key to fill in |
|-------------|----------------|
| `triage/` | `ANTHROPIC_API_KEY` |
| `prosecutor/` | `ANTHROPIC_API_KEY` |
| `defender/` | `FEATHERLESS_API_KEY` |
| `judge/` | `OPENAI_API_KEY` |

The Band URLs are already pre-filled — don't change them.

### Getting your API key

**Featherless** (`defender/`):
1. Go to [featherless.ai](https://featherless.ai) and click **Sign up**
2. Create an account
3. Go to [featherless.ai/account/api-keys](https://featherless.ai/account/api-keys)
4. Copy your API key and paste it as `FEATHERLESS_API_KEY` in `.env`

**Anthropic** (`triage/`, `prosecutor/`):
1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in
2. Click **API Keys** in the left sidebar → **Create Key**
3. Copy and paste it as `ANTHROPIC_API_KEY` in `.env`

**OpenAI** (`judge/`):
1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and sign in
2. Click **Create new secret key**
3. Copy and paste it as `OPENAI_API_KEY` in `.env`

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

Your agent is now live. Go to Band, open a room with it, and send it a message to confirm it responds.

---

## Troubleshooting

**Agent doesn't respond in Band** — make sure `python3 agent.py` is still running in your terminal. It stops when you close the terminal.

**`ModuleNotFoundError`** — run `pip3 install -r requirements.txt` again.

**API key error** — double-check the key in your `.env` file has no extra spaces or quotes.

---

> **Never commit** `agent_config.yaml` or `.env` — they contain your private keys.
