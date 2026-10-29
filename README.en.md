<div align="center">

<img src="docs/banner.svg" alt="claude-calls-you" width="100%">

**[العربية](README.md) · [English](README.en.md)**

</div>

# claude-calls-you 📞

Let Claude Code work while you are away. When it needs you, it **phones you and talks**: to report what it finished, to get your approval before a risky step, or to take a new command from your voice.

## Why

| Problem | Solution |
|---|---|
| The agent blocks waiting for approval while you are away | It calls, asks, and you answer by voice |
| A long task finishes and you do not know | A short call tells you the result |
| You fear a risky step (delete, deploy, pay) without consent | **Nothing sensitive runs without an explicit yes**; on any doubt it never assumes consent |
| You want to control call frequency | Say it: "call me only for approvals, twice an hour max" |

## How it works

<img src="docs/architecture.svg" alt="architecture" width="100%">

Claude Code calls the MCP tool `call_user`, `voice_bridge` asks Twilio to dial you, a free `cloudflared` tunnel exposes the local webhook, and an ElevenLabs voice agent talks with you and returns `approved`, `rejected` or `instructions`.

## Quick start (let the agent install everything)

1. Prepare [Twilio](https://www.twilio.com) (a number and your verified phone) and [ElevenLabs](https://elevenlabs.io) (API key with all permissions).
2. In Claude Code, inside your project folder, paste:

```text
Clone https://github.com/flymefy/claude-calls-you, read AGENT_INSTALL.md and docs/voice-call-guide.pdf, then install and configure the voice-call system on this machine (or server), and register the tool, skill and hooks. Never ask me to paste keys in chat; tell me which .env fields to fill myself. Ask before any test call.
```

3. Fill the `.env` fields the agent lists, restart Claude Code, then say: **"use call_user and call me"**.

## Manual install

```bash
git clone https://github.com/flymefy/claude-calls-you.git && cd claude-calls-you
python voice_bridge/setup.py
# fill voice_bridge/.env, then
python voice_bridge/setup.py --install
python voice_bridge/selftest.py check
```

## Features

- Real voice conversation (Arabic or any language) via an ElevenLabs agent, or a recorded message with speech or keypad reply.
- Spoken commands are read back and confirmed before reaching the agent.
- Hourly call cap, hook cooldown, and a `phone-call-user` skill defining when and how to call.
- Runs on your laptop or a server, no domain or static IP needed (cloudflared quick tunnel).
- Secrets stay in a local `.env`.

## Security

Never share or commit `.env` (it is git-ignored), rotate keys after testing, and never paste keys in chat.

## License

MIT.
