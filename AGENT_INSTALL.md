# Agent install instructions

**Audience: the coding agent (Claude Code) that the user asked to install this project.** Reply to the user in the language they write in. Execute the steps in order and report each result briefly. The illustrated guide for the human is `docs/voice-call-guide.pdf` (pages 10 to 16 mirror this file and add the ElevenLabs agent spec and the skill text).

## 0. What you are installing

An MCP tool `call_user(message, wait_for_reply, timeout_sec)` that phones the user. Flow: Claude Code calls the tool, `voice_bridge/server.py` (stdio MCP) calls `bridge.notify()`, which asks Twilio to dial the user. In **agent** mode (recommended) Twilio fetches TwiML from a local Flask webhook exposed by a free `cloudflared` quick tunnel; the webhook registers the call with an ElevenLabs Conversational AI agent, which talks to the user and returns a decision (`approved`, `rejected`, `instructions`) read back through the ElevenLabs conversations API. Hooks (Stop, Notification) give short informational calls with a cooldown. A global skill `phone-call-user` and a CLAUDE.md rule tell Claude when to call. All code already exists in `voice_bridge/`. Do not rewrite it; install and configure it.

## 1. Hard rules

- Never ask the user to paste keys in chat. Never print `.env` values. Tell the user which fields to fill, then verify only that they are non-empty.
- Do not place a test call that spends credit until the user explicitly agrees.
- Never commit `.env`, `calls.log`, `state.json`, `output/` (already in `.gitignore`).

## 2. Get the code and discover

- If this repository is not already on disk, `git clone https://github.com/flymefy/claude-calls-you.git` into the user's project folder (or `~/twilio` on a server) and work inside it. `voice_bridge/` is the system folder.
- Detect OS and Python (3.10+). Check `claude --version`.

## 3. Install

- Linux/server: create `~/twilio/.venv` and use its python for every command (and in the MCP registration and hooks).
- `python voice_bridge/setup.py` installs requirements, downloads the local Piper Arabic model (fallback TTS, about 63 MB) and creates `.env` from `.env.example`. If `piper-tts` fails to install (for example on a very new Python), install the other requirements (`flask twilio mcp python-dotenv requests`) and continue; Piper is only a fallback when `TTS_ENGINE=elevenlabs`.
- Install `cloudflared`: Windows `winget install Cloudflare.cloudflared`; macOS `brew install cloudflared`; Linux from the official GitHub release (.deb or binary in `/usr/local/bin`). If it is not on PATH (Windows), set `CLOUDFLARED_PATH` in `.env`.

## 4. Secrets (`voice_bridge/.env`)

On Linux run `chmod 600 .env`. The user fills these themselves (phone numbers in E.164 format with a leading +):

| Key | Meaning |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio console (or `TWILIO_API_KEY` + `TWILIO_API_SECRET`) |
| `TWILIO_FROM_NUMBER` | Twilio number that calls the user |
| `MY_PHONE_NUMBER` | The user's phone (must be verified in Twilio on a trial account) |
| `ELEVENLABS_API_KEY` | ElevenLabs key with all permissions |
| `ELEVENLABS_AGENT_ID` | Filled by you in step 6 |

## 5. Settings (ask the user first, then write them to `.env`)

- `NOTIFY_MODE=agent` (voice conversation) or `twilio` (recorded message with speech or keypad reply).
- `TTS_ENGINE=elevenlabs`, `ELEVENLABS_TTS_MODEL=eleven_multilingual_v2`, `ELEVENLABS_VOICE_ID`: an Arabic-capable voice available to the account. The default in `.env.example` may not exist for them; list the voices and let the user choose.
- `VOICE_REPLY=speech`, `TWILIO_SPEECH_LANG` matching the user's language (`ar-SA`, `en-US`, `tr-TR`, ...).
- `MAX_CALLS_PER_HOUR` (default 6), `HOOK_COOLDOWN_SEC` (default 600). Ask when the user wants calls (task finished, approval needed, waiting for a command) and encode it in the skill's "When to call" section.

## 6. ElevenLabs voice agent (needed for `NOTIFY_MODE=agent`)

If an ElevenLabs MCP server is connected, create the agent with it; otherwise call `POST https://api.elevenlabs.io/v1/convai/agents/create` with the header `xi-api-key` read from `.env` (never echo it). Use exactly the specification on pages 14 and 15 of `docs/voice-call-guide.pdf` (name, language `ar`, first message, system prompt, data collection, `end_call` tool). Put the returned id in `ELEVENLABS_AGENT_ID`. Agent mode does not need `eleven-setup`; run `python voice_bridge/selftest.py eleven-setup` only for `NOTIFY_MODE=elevenlabs`.

## 7. Register with Claude Code

- `python voice_bridge/setup.py --install` registers the MCP server `voice-call` (user scope), adds Stop and Notification hooks to `~/.claude/settings.json`, appends the rule to `~/.claude/CLAUDE.md`, and copies the skill to `~/.claude/skills/phone-call-user/SKILL.md`.
- If `claude` is not on PATH (Windows PowerShell): `python voice_bridge/register_mcp.py`.
- Check that `~/.claude/skills/phone-call-user/SKILL.md` exists and matches `voice_bridge/skill/phone-call-user/SKILL.md`. Apply the user's chosen "when to call" rule to it. `~/.claude` is per machine, so repeat on every machine or server.

## 8. Verify at zero cost

- `python voice_bridge/selftest.py check` reports nothing missing.
- `claude mcp list` shows `voice-call`.
- Ask permission before any real call (`selftest.py call --yes` or `eleven-call --yes`).

## 9. Finish

Summarize what was installed and what is still missing. Tell the user to restart Claude Code, then say: "use call_user and call me". Remind them: never share `.env`, rotate Twilio and ElevenLabs keys after testing, and repeat the install on every machine or server where they want the phone feature.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `not_configured` | A field is empty in `.env`; run `selftest.py check`. |
| Tunnel fails | Install cloudflared or set `CLOUDFLARED_PATH`; or set `PUBLIC_BASE_URL` and `LOCAL_PORT` for a fixed domain. |
| No call on a Twilio trial | The destination must be a verified number. |
| Speech misheard | Set `TWILIO_SPEECH_LANG` to the user's language. |
| `rate_limited` | Hourly cap reached; wait or raise `MAX_CALLS_PER_HOUR`. |
| Tool missing | Restart Claude Code fully; check `claude mcp list`. |
