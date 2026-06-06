---
name: mavis-brain-integration
description: Use when the user mentions "Mavis Brain", a Synology NAS-hosted long-term memory service, or wants Hermes to share / read / write memories across devices. Covers the Mavis Brain REST API (port 5188), the seven memory categories, the 44 synonym semantic groups, the Tailscale cross-device network, and how to wire a Hermes skill so every Hermes session auto-syncs with the user's shared brain.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [mavis, brain, memory, synology, nas, tailscale, cross-device, long-term-memory]
    related_skills: [hermes-agent, hermes-api-server]
---

# Mavis Brain — Cross-Device Long-Term Memory for Hermes

## Overview

Mavis Brain is a **self-hosted, long-term memory service** running on the user's Synology NAS (DS220j). It exposes a FastAPI REST API on port 5188 that any agent on the Tailscale network can call. It uses an **add-only, mem0-inspired architecture** — memories accumulate, never overwrite — with **multi-signal search** (semantic + category + entity), **evolution tracking**, and **cross-device sync** by design.

The user's Brain already has **41+ memories** in 7 categories (preference, habit, skill, workflow, interest, fact, context). The user guide lives at `~/Desktop/mavis-brain-user-guide.md`. The source skill that Mavis (a different agent) uses is at `~/.minimax/skills/mavis-brain/` — but **Hermes has no equivalent**. This skill is the bridge: it tells Hermes how to read, write, and reason about the user's Brain, so knowledge persists across Telegram bots, Open WebUI, desktop clients, and any future Hermes front-end.

The user has a clear preference: **"no matter which device has Hermes attached, it should know what I've done before."** This skill exists to make that work.

## When to Load

- User mentions "Mavis Brain", "Brain server", "shared memory", "NAS memory", or "cross-device memory"
- User asks why a Telegram bot doesn't know what they discussed in Open WebUI
- User references `100.76.149.19:5188` (the Brain server URL)
- User asks "how do I make Hermes remember X across all my devices"
- You need to read the user's preferences / habits / past workflows before responding
- You need to log a learning event, error pattern, or newly-acquired skill to the shared brain
- A new Hermes session starts and you want to pull relevant context from Brain (instead of starting blank)

## When NOT to Load

- User is asking about a different memory system (Honcho, Mem0, Hindsight, Supermemory, ByteRover — those are separate, cloud-based)
- User wants local-only `~/.hermes/memories/` editing (that's the `hermes-agent` skill's territory)
- The Brain server is unreachable (Tailscale down, NAS off) — degrade gracefully, don't pretend to remember

## Architecture (what's where)

```
                   ┌─── MacBook (Tailscale, 100.x) ──┐
                   │                                 │
                   ├─── iPhone (Tailscale) ──────────┤
Jason ─────────────┼─── iPad (Tailscale) ────────────┼──────── Synology NAS DS220j
                   │                                 │         100.76.149.19:5188
                   ├─── Win Laptop (Tailscale) ──────┤         "Mavis Brain" (FastAPI)
                   │                                 │         SQLite + memory.json
                   └─── Win Desktop (Tailscale) ─────┘
```

- **Brain server:** `http://100.76.149.19:5188`
- **API key (header):** `x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85`
- **Tailscale required** for off-LAN access; on the home LAN, the 100.x IP works directly
- **Local mirror:** `~/.mavis/agents/mavis/memory/MEMORY.md` (auto-synced per session by Mavis, not by Hermes — Hermes must do its own sync if it wants this)
- **Source of truth on NAS:** `/volume2/homes/yasonok02061/mavis-brain/memories.json`

## API Quick Reference

All requests use the `x-api-key` header. No body needed for `GET`s; JSON body for `POST`/`DELETE`.

### Health check (no auth)
```bash
curl -s -m 5 http://100.76.149.19:5188/
# → {"status":"running","architecture":"mem0-inspired add-only memory"}
```

### Stats
```bash
curl -s http://100.76.149.19:5188/brain/stats \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
# → {"total_memories": 41, "by_category": {...}, "by_source": {...}}
```

### Add a memory
```bash
curl -X POST http://100.76.149.19:5188/memory/add \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d '{
    "content": "Jason prefers concise responses, no bullet points",
    "category": "preference",
    "source": "learned",
    "tags": ["communication","style"]
  }'
```

### Semantic search (PRIMARY interface — use this)
```bash
curl -X POST http://100.76.149.19:5188/brain/relevant \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d '{"context": "被動收入投資", "limit": 5}'
# Brain expands synonyms via 44 semantic groups before searching
```

### Keyword search
```bash
curl -X POST http://100.76.149.19:5188/memory/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d '{"query": "ETF", "limit": 5}'
```

### Delete
```bash
# Single memory by ID
curl -X DELETE http://100.76.149.19:5188/memory/{id} \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"

# Whole category
curl -X DELETE "http://100.76.149.19:5188/memory?category=test" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
```

## The Seven Categories (with weights)

| Category | Purpose | Weight |
|----------|---------|--------|
| `preference` | Preferences, habits, tastes | **3.0** (highest) |
| `habit` | Daily behaviors, tool choices | 2.5 |
| `skill` | Skills, professional abilities | 2.0 |
| `workflow` | How tasks are done, project operations | 2.0 |
| `interest` | Interests, learning directions | 1.8 |
| `fact` | Objective facts, settings, identity | 1.5 |
| `context` | Situation, background | 1.5 |

Prefer `preference` and `habit` for things the user **wants you to remember next time**. Use `fact` only for stable identity/config. Avoid `context` for anything durable.

## Semantic Groups (44 synonym sets — partial list)

```
投資理財 → ETF, 被動收入, 股票, 基金, 債券, 理財, 投資, 退休, 複利
工作     → ROADM, Card Expansion, Module Expansion, 施工, 報告
工具     → SecureCRT, PuTTY, Vercel, GitHub, Next.js, Mavis
網站     → SEO, 部落格, 文章, Vercel, GitHub push, URL, slug
溝通     → 簡潔, bullet, 問候語, 直接, 偏好
設備     → Mac, Windows, NAS, DS220j, Synology
自動化   → cron, 排程, Mavis, Python script
```

When searching, use **one of these canonical terms** in the `context` field — Brain expands to the full group automatically. Avoid obscure jargon; the user will search using everyday words.

## Device IDs (for evolution logging)

When logging an `evolution` event, use the device that produced the learning:

| Device | ID |
|---|---|
| MacBook (this user's primary) | `ryans-macbook-pro` |
| iPhone | `iphone-jason` |
| iPad | `ipad-jason` |
| Windows laptop | `win-laptop-jason` |
| Windows desktop | `win-desktop-jason` |

## Auto-Learning Rules (when to add to Brain)

Add a memory automatically when:
1. User **corrects** your behavior or preferences ("don't do X", "I prefer Y")
2. User **mentions a habit or preference** ("I always...", "I never...")
3. A task **completes successfully** (log an `evolution` event with `task_success`)
4. A task **fails** (log an `error` pattern for future avoidance)
5. User **changes communication style** ("stop using bullets", "be more direct")

Do NOT add:
- Trivia that won't matter next time
- Anything already in Brain (check first with `relevant`)
- Test data with `category=test` (clean it up after)

## Auto-Recall Rules (when to search Brain)

Search Brain automatically when:
- **Starting a new task** — check for related skills/workflows
- **Writing a response** — pull user preferences to match style
- **Making a decision** — check for past patterns / errors
- **User asks "do you remember..."** — explicit recall trigger
- **User references past work** ("the SEO project", "the aquarium site")

The `brain/relevant` endpoint (semantic, not keyword) is the **primary interface** for this. Default to it.

## Hermes-Specific Integration Patterns

### Pattern 1: Session-start sync
At the start of every Hermes session, call `brain/relevant` with a context summarizing the user's likely intent. Inject top results into the agent's system context as `[from Mavis Brain]` prefixed notes. Do not surface the raw API to the user.

### Pattern 2: Session-end commit
At the end of a session (or after a non-trivial exchange), analyze the conversation for durable learnings. For each, call `memory/add` with the right category. Log a `brain.evolve` event with `device_id=ryans-macbook-pro` for successful outcomes.

### Pattern 3: Per-message preference check
For the first message of a session, run a single `brain/relevant` query like `context: "user preferences communication style"` and use the result to shape tone. Do not call Brain for every message — it adds latency.

### Pattern 4: Avoid the local-only trap
`~/.hermes/memories/` is **per-device**. It does NOT sync. Anything you write there dies when the user switches devices. Brain is the only place that survives across Tailscale-connected devices. Default to Brain for anything cross-device; use `~/.hermes/memories/` only for environment-specific state (e.g., this device's local CLI quirks).

## Common Pitfalls

### Pitfall 1 — Treating `~/.hermes/memories/` as shared memory
It is **not**. It's a per-device local file. Use Brain.

**Worked example (2026-06-06):** to get Brain context into every Hermes session, the agent appended a 7-line "Mavis Brain sync" block to `~/.hermes/memories/MEMORY.md` — high-weight preferences, identity, sync tool location. This is **not** Brain auto-pull (that's Pattern A in the recipe reference), but it is a pragmatic v0 that works for Hermes CLI / Open WebUI / Telegram because all three frontends read `MEMORY.md` at session start. Pin the content to Brain-derived high-weight entries only; do **not** let raw session logs flow into `MEMORY.md` — that dilutes signal and bloats prompt tokens.

### Pitfall 2 — Posting secrets into Brain content
Brain is on a NAS behind Tailscale, not encrypted-at-rest by default. Do not write API keys, passwords, or tokens into `content`. The user has already made this mistake once in this session (Telegram bot token pasted into chat). Don't repeat it for them.

**Also: `~/.hermes/.env` is read-redacted by the agent tool surface** (write OK, read denied; token-shaped strings in your own code get `***` masked). So once a token leaks into the session transcript, it lives in `~/.hermes/sessions/*.db` and may be in `~/.hermes/logs/*.log` — **not redacted in the source DB, only in tool output**. Treat the token as compromised the moment it lands in chat, even if subsequent tool calls show `***`.

### Pitfall 2b — `sync.sh pull` does NOT return strict newest-first; it can hide fresh writes
`brain/search` with an empty `query` returns memories ranked by relevance + recency, not pure timestamp order. After a fresh `add`, `pull 5` may not show the new entry. To confirm a write succeeded: use `stats` (compare `total_memories` before/after) or `search` with a unique tag. The script warns about this on every `pull`.

### Pitfall 2c — Don't write a new `MemoryProvider` plugin in-tree
The user asked "make Hermes talk to Brain" and the agent initially considered writing a `~/.hermes/hermes-agent/plugins/memory/mavis_brain/` plugin. **Don't.** Per Hermes policy (May 2026, AGENTS.md §"Memory-provider plugins"): **no new in-tree memory providers.** New backends must ship as standalone plugin repos. The pragmatic path is a Hermes **skill + shell script** (the one in `scripts/sync.sh`), not a core plugin. The skill approach costs ~30 minutes, the plugin approach costs a PR review and external repo.

### Pitfall 3 — Brain unreachable → silent fallback
If the Brain health check (`curl http://100.76.149.19:5188/`) times out or returns non-200, **say so**. Do not pretend to remember things; degrade to `~/.hermes/memories/` and tell the user Brain is offline. Common causes: Tailscale disconnected, NAS powered off, API key rotated.

### Pitfall 4 — Adding too much, diluting signal
41 memories is a healthy size. Each new memory must be **non-obvious and durable**. "User asked about X today" is not a memory — that's a session log. Reserve Brain for things the user will want you to know next month.

### Pitfall 5 — Synonym group miss
If you search with a term Brain doesn't have a synonym for, results will be empty. When `brain/relevant` returns 0 hits, try a broader or canonical term from the synonym groups above. If still empty, the memory really doesn't exist — don't fabricate.

### Pitfall 6 — Conflicting `hermes config set` semantics
The Brain integration is **outside** Hermes's config system. Don't try to wire it via `hermes config set`. Use a separate script or hook that calls the Brain REST API directly. The existing `~/.minimax/scripts/mavis-brain-client.py` is a reference implementation you can read.

### Pitfall 7 — Telegram bot session ≠ Brain session
A Telegram chat in Hermes uses a different `session_id` from Brain. The user asked about this: "Will Telegram know what we discussed here?" Answer: **no, sessions are isolated** — but **memories stored in Brain are shared**. So if you commit a learning to Brain at the end of a Telegram session, the next Open WebUI session will see it. The user wants this behavior. Use it.

## Verification Checklist

After wiring Hermes to Brain, verify:

- [ ] Health check responds within 1s from the active device: `curl -s http://100.76.149.19:5188/`
- [ ] `brain/stats` shows the expected memory count (compare to last known)
- [ ] Test add: write a sentinel memory with a unique tag, search for it, confirm presence
- [ ] Test semantic: query with a synonym-group term (e.g. `被動收入` for the `投資理財` group), confirm the canonical match comes back
- [ ] Test cleanup: delete the sentinel, confirm `total_memories` decremented

## One-Shot Recipes

### Bootstrap: check Brain is healthy and report stats
```bash
curl -s -m 5 http://100.76.149.19:5188/ && \
curl -s http://100.76.149.19:5188/brain/stats \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
```

### Bulk-import: dump Brain to a local JSON for offline review
```bash
curl -s -X POST http://100.76.149.19:5188/memory/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d '{"query":"","limit":1000}' > /tmp/brain-dump-$(date +%Y%m%d).json
```

### Cross-device smoke test
1. From MacBook, add a memory with `device_id=ryans-macbook-pro`
2. From another Tailscale device, run the bootstrap recipe above and confirm `total_memories` increased
3. From the second device, search for the new memory's content — should appear

## References

- `~/Desktop/mavis-brain-user-guide.md` — user-authored Brain operations guide
- `~/.minimax/skills/mavis-brain/SKILL.md` — Mavis's own integration skill (read for reference, not auto-applicable to Hermes)
- `~/.minimax/skills/mavis-brain/CROSS-DEVICE-SETUP.md` — Tailscale + multi-device setup
- `~/.minimax/scripts/mavis-brain-client.py` — reference Python client (5.3 KB)
- `~/.minimax/scratchpads/*/workspace/mavis_brain_server.py` — Brain server source (FastAPI, SQLite)
- `references/hermes-integration-recipe.md` — concrete Hermes-side wiring cookbook (session-start/end hooks, failure modes, smoke test)
- `scripts/sync.sh` — bash wrapper exposing `stats` / `pull` / `add` / `search` / `relevant` / `delete` subcommands. Works from any Hermes frontend via the terminal tool.
