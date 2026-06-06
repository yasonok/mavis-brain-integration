# mavis-brain-integration — Cross-Device Long-Term Memory

Hermes ↔ Mavis Brain (Synology NAS) bridge. Install once per device, and that device can read/write the same shared memory as every other device on your Tailscale network.

## TL;DR for a new device

```bash
# 1. Make sure Hermes is installed (https://hermes-agent.nousresearch.com/docs/getting-started/installation)
hermes --version

# 2. Make sure Tailscale is connected and you can reach the NAS
curl -s http://100.76.149.19:5188/   # should print {"status":"running"...}

# 3. Run the installer
curl -sSL https://raw.githubusercontent.com/yasonok/mavis-brain-integration/main/install.sh | bash

# 4. Verify
hermes-with-brain "what do you know about me?"
```

## What the installer does

| Step | What | Why |
|------|------|-----|
| 1 | Verifies `hermes` is on PATH | Don't proceed if Hermes missing |
| 2 | `curl $BRAIN_URL/` | Tailscale + NAS reachable? |
| 3 | `curl /brain/stats` with API key | API key still valid? |
| 4 | Copies skill to `~/.hermes/skills/mavis-brain-integration/` | Hermes needs the SKILL.md to discover the integration |
| 5 | Drops `~/.local/bin/hermes-with-brain` wrapper | Auto-injects Brain context into every Hermes session |
| 6 | Writes `~/.mavis/config/brain.json` with device_id | For other tools (Mavis, scripts) to find the same Brain |
| 7 | Smoke test (sentinel add/search/delete) | Confirms write+read works on this device |

Re-running is safe — it overwrites the wrapper and config but never touches Brain contents.

## What you get

### `hermes-with-brain` command

Same as `hermes`, but before each session starts it:
1. Pulls the top 8 relevant memories from Brain
2. Injects them as a `[from Mavis Brain]` block in the system context
3. Forwards the call to real `hermes`

So `hermes-with-brain` always knows your preferences, your workflows, your skills.

### `~/.hermes/skills/mavis-brain-integration/scripts/sync.sh`

Six subcommands:
- `stats` — Brain health + memory counts
- `pull [N]` — show N most recent memories
- `add "TEXT" [category]` — write a new memory
- `search "QUERY" [N]` — keyword search
- `relevant "CONTEXT" [N]` — semantic search (synonym-expanded)
- `delete ID` — delete by id

### `~/.mavis/config/brain.json`

Standard config format, also read by Mavis (the other agent) so both agents agree on which Brain is "yours".

## Cross-device smoke test

After installing on two devices:

**On device A:**
```bash
~/.hermes/skills/mavis-brain-integration/scripts/sync.sh add "Hello from device A"
```

**On device B:**
```bash
~/.hermes/skills/mavis-brain-integration/scripts/sync.sh search "Hello from device A"
# Should return the new memory
```

If it works, Brain is the shared memory for all your devices.

## Architecture

```
┌─── MacBook Pro (this device) ──┐
│  ~/.hermes/skills/mavis-brain-integration/ │
│  ~/.local/bin/hermes-with-brain            │
└──────────────┬──────────────────────────────┘
               │ Tailscale (100.x)
               │
┌──────────────┴──────────────────────────────┐
│  Synology NAS (DS220j)                       │
│  100.76.149.19:5188                          │
│  Mavis Brain server (FastAPI + SQLite)        │
│  41+ memories, 7 categories                   │
└──────────────┬──────────────────────────────┘
               │
       ┌───────┼───────┐
       │       │       │
   iPhone   iPad   Windows
   (TG)     (TG)   (TG/CLI)
```

Every device that runs the installer can read/write the same Brain. Memories accumulate forever (add-only). User preferences, workflows, and skills follow you everywhere.

## Why a wrapper script (not a Hermes plugin)?

Hermes policy (May 2026): **no new in-tree memory providers**. The proper way to add a memory backend is a standalone plugin repo + PR. That's a 2-3 day project. The wrapper script is the pragmatic 5-minute equivalent:

- `hermes-with-brain` calls Brain once per session, then defers to real `hermes`
- No core code modified
- Works for `hermes --tui`, `hermes` REPL, anything that shells out

If you need per-message Brain queries (not just per-session), wire it into your Open WebUI custom function or your own agent loop.

## Troubleshooting

### "Cannot reach $BRAIN_URL"
- Tailscale connected? `tailscale status`
- NAS powered on?
- On home LAN, try the LAN IP (`192.168.x.x:5188`) instead

### "API key rejected"
- Key may have been rotated. New key: `cat ~/mavis-brain/.apikey` on the NAS
- Re-run installer with `--api-key NEW_KEY`

### "hermes-with-brain: command not found"
- `~/.local/bin` not on PATH
- Add: `export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`

### "Brain returned 0 results for a term I know is in there"
- Likely a synonym-group miss. Try a canonical term from the SKILL.md reference

## See also

- `SKILL.md` — the integration description Hermes reads
- `references/hermes-integration-recipe.md` — deeper patterns (session-end commit, per-message preference check)
- `scripts/sync.sh --help` — quick command reference
- `scripts/verify_brain.py` — full health check script
