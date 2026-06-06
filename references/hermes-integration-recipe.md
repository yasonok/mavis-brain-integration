# Hermes ↔ Mavis Brain Integration Recipe

Concrete steps discovered 2026-06-06 to wire Hermes (agent, API server, Telegram, Open WebUI, desktop) into Mavis Brain. The skill above describes the architecture; this file is the **cookbook**.

## Current environment (June 2026)

- **MacBook Pro (Intel i5-8259U, 8 GB, macOS 15.7.3)** — primary device
- **Hermes CLI v0.16.0** at `~/.hermes/hermes-agent/`
- **Hermes API server** on `127.0.0.1:8642` (`API_SERVER_KEY=yasonok02061`)
- **Telegram bot** `@Andy_gemini3pro_bot` (id `8029427419`) — connected, polling, user `Jason` (`7825900351`) on allowlist
- **Open WebUI 0.7.2** on `127.0.0.1:8080`, admin `yasonok`
- **Brain server** at `100.76.149.19:5188` (Synology NAS DS220j, Tailscale)
- **41 memories** in Brain as of 2026-06-06 22:45 — workflow 17, fact 9, preference 6, interest 5, skill 2, habit 2
- **Existing scripts/tools** (all under `~/.minimax/`, not yet wired into Hermes):
  - `~/.minimax/scripts/mavis-brain-client.py` — reference Python client
  - `~/.minimax/skills/mavis-brain/{SKILL.md,CROSS-DEVICE-SETUP.md,AUTO-START-SETUP.md}`
  - `~/.minimax/scratchpads/mvs_82a7c0487279466392d7aad88889e516/workspace/mavis_brain_server.py` — Brain server source

## The three integration patterns that actually matter

### Pattern A: Session-start auto-pull (highest ROI)
On every new Hermes session, before the user's first message:

```python
import requests
resp = requests.post(
    "http://100.76.149.19:5188/brain/relevant",
    headers={"x-api-key": "0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"},
    json={"context": "user preferences habits skills workflows", "limit": 8},
    timeout=3,
)
memories = resp.json().get("result", [])
# Inject into the agent's system context as a "[from Mavis Brain]" block
```

Result: 1 round-trip (0.16s typical), Hermes starts every session knowing the user's preferences.

### Pattern B: Session-end auto-commit
After a non-trivial exchange, classify and commit:

```python
def commit_to_brain(content, category, tags=None, source="learned", device="ryans-macbook-pro"):
    return requests.post(
        "http://100.76.149.19:5188/memory/add",
        headers={"x-api-key": "0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"},
        json={"content": content, "category": category, "tags": tags or [],
              "source": source, "device_id": device, "user_id": "jason"},
        timeout=3,
    )
```

Use sparingly — Brain is small (41 entries). Reserve for things that will matter in 30 days.

### Pattern C: Per-message preference check (only on first message)
The first message of a session triggers one `brain/relevant` call. Subsequent messages skip it. This avoids per-message latency while still personalizing.

## Where to plug in (Hermes-side hooks)

| Layer | Hook point | What to do |
|---|---|---|
| `hermes-cli` (`hermes` command) | wrapper script in `~/.local/bin/hermes` that calls `hermes` after running the session-start sync | Easiest, no Hermes core changes |
| `hermes-api-server` (port 8642) | monkey-patch `gateway/platforms/api_server.py` to call Brain on session start | Medium effort |
| Telegram gateway (`gateway/platforms/telegram.py`) | add Brain sync to the `agent:main:telegram:dm:*` session start | Medium effort |
| Open WebUI 8080 | write a custom Open WebUI **function** that calls Brain on first user message of a chat | High effort, optional |
| Hermes Desktop (when build completes) | same as CLI — wrapper or first-message hook in `apps/desktop/` | High effort, optional |

**Recommended first step:** the CLI wrapper. It covers `hermes --tui`, `hermes` REPL, and any script that shells out.

## What NOT to do (learned the hard way in this session)

1. **Don't store API keys in Brain content.** Brain is on a NAS behind Tailscale, not encrypted at rest. The user already pasted a Telegram bot token into a chat session — that mistake is permanent (it lives in session DB, .env, possibly log files). Don't add to the damage.
2. **Don't use `~/.hermes/memories/` for cross-device state.** It's per-device. Brain or bust.
3. **Don't try to wire Brain via `hermes config set`.** Brain is a separate service; `hermes config set` only touches `~/.hermes/config.yaml` and `~/.hermes/.env`. Write a script.
4. **Don't `rm -rf ~/.hermes` to "start fresh" without backing up Brain separately.** Brain lives on NAS, not under `~/.hermes`, so it's safe — but if you conflate the two, you'll think you lost memories when you didn't.

## Verification (smoke test for a fresh integration)

```bash
# 1. Reachability
curl -s -m 5 http://100.76.149.19:5188/ | grep -q "running" && echo "OK"

# 2. Auth
STATS=$(curl -s http://100.76.149.19:5188/brain/stats \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85")
echo "$STATS" | python3 -m json.tool | head -10

# 3. Sentinel add + search + delete roundtrip
SENTINEL="mavis-brain-integration-smoke-$(date +%s)"
curl -s -X POST http://100.76.149.19:5188/memory/add \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d "{\"content\": \"$SENTINEL\", \"category\": \"test\", \"source\": \"smoke-test\"}" > /dev/null

sleep 1
FOUND=$(curl -s -X POST http://100.76.149.19:5188/memory/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d "{\"query\": \"$SENTINEL\", \"limit\": 5}")
echo "$FOUND" | grep -q "$SENTINEL" && echo "✅ search found sentinel" || echo "❌ search missed"

# 4. Clean up the test category
curl -s -X DELETE "http://100.76.149.19:5188/memory?category=test" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
```

If all four pass, the integration is wired correctly.

## Failure modes the user has hit

- **Brain returns 0 results for a topic the user swears is in there.** → likely a synonym-group miss. Try a more canonical term. If still empty, the memory really isn't there; check `brain/stats` for category counts and verify the memory was committed.
- **Tailscale disconnected.** All requests to `100.76.149.19:5188` time out. Hermes should fall back to `~/.hermes/memories/` and tell the user Brain is offline.
- **API key rotated.** 401 from every endpoint. New key lives in `~/mavis-brain/.apikey` on the NAS. Update the script.
- **NAS off.** Tailscale may still resolve, but connect attempts will hang for 30+ seconds. Always set a 3-5s timeout on Brain calls so the agent doesn't stall.

## Files this integration will create (when you do implement it)

- `~/.local/bin/hermes-with-brain` — wrapper script (or a Python entry point)
- `~/.hermes/skills/mavis-brain-integration/` — already exists as of 2026-06-06 (this skill)
- `~/.hermes/state/brain_cache.json` — optional local cache so per-session pulls are <1 round-trip
- Optional: a cron job that runs `brain/evolve` events hourly with task-success counts

## Open questions (not blocking)

- Should Brain `content` be encrypted with a user-supplied passphrase before writing? (Today: no.)
- Should Hermes prompt the user before committing a `preference` memory? (Today: it shouldn't — the user has stated "no matter which device, it should know what I've done" — implying auto-commit is the desired default. But high-stakes preferences deserve confirmation.)
- What happens when Brain is the **only** copy of a memory and the NAS dies? (Today: memory is gone. RAID on the NAS is the user's responsibility, not Hermes's.)
