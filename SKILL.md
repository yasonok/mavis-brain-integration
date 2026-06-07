---
name: mavis-brain-integration
description: "Bridge Hermes to the Mavis Brain long-term memory service on Synology NAS via Tailscale. Covers the REST API (port 5188), seven memory categories, M3 LLM auto-extraction from conversations, client-side smart layer (forgetting curve, TTL, pinned, dedup, conflict detection, summarization), gateway hook pattern for session-end auto-sync, and 6 known server-side bugs that require client workarounds. Use when the user mentions Mavis Brain, cross-device long-term memory, or wants Hermes to remember durable facts across Telegram / Open WebUI / Desktop."
version: 1.2.0
author: Hermes Agent
license: MIT
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [mavis, brain, memory, synology, nas, tailscale, cross-device, long-term-memory, m3, llm-extraction, forgetting-curve, gateway-hooks]
    related_skills: [hermes-agent, hermes-api-server, hermes-cron-schedules]
---

# Mavis Brain — Cross-Device Long-Term Memory for Hermes

## Overview

Mavis Brain is a **self-hosted, long-term memory service** running on the user's Synology NAS (DS220j). It exposes a FastAPI REST API on port 5188 that any agent on the Tailscale network can call. It uses an **add-only, mem0-inspired architecture** — memories accumulate, never overwrite — with **multi-signal search** (semantic + category + entity), **evolution tracking**, and **cross-device sync** by design.

The user's Brain already has **50+ memories** in 7 categories (preference, habit, skill, workflow, interest, fact, context). The user guide lives at `~/Desktop/mavis-brain-user-guide.md`. The source skill that Mavis (a different agent) uses is at `~/.minimax/skills/mavis-brain/` — but **Hermes has no equivalent**. This skill is the bridge: it tells Hermes how to read, write, and reason about the user's Brain, so knowledge persists across Telegram bots, Open WebUI, desktop clients, and any future Hermes front-end.

The user has a clear preference: **"no matter which device has Hermes attached, it should know what I've done before."** This skill exists to make that work.

## When to Load

- User mentions "Mavis Brain", "Brain server", "shared memory", "NAS memory", or "cross-device memory"
- User asks why a Telegram bot doesn't know what they discussed in Open WebUI
- User references `100.76.149.19:5188` (the Brain server URL)
- User asks "how do I make Hermes remember X across all my devices"
- You need to read the user's preferences / habits / past workflows before responding
- You need to log a learning event, error pattern, or newly-acquired skill to the shared brain
- A new Hermes session starts and you want to pull relevant context from Brain (instead of starting blank)
- A user pastes a session log, a long conversation, or a /from-session request — `extract_facts.py` is the entry point
- A user wants weekly / scheduled Brain review, conflict detection between old and new facts, or summarization of stale memories
- Any task involving MiniMax M3 prompt design for structured extraction

## When NOT to Load

- User is asking about a different memory system (Honcho, Mem0, Hindsight, Supermemory, ByteRover — those are separate, cloud-based)
- User wants local-only `~/.hermes/memories/` editing (that's the `hermes-agent` skill's territory)
- The Brain server is unreachable (Tailscale down, NAS off) — degrade gracefully, don't pretend to remember
- User is asking about general cron / scheduled job patterns not related to Brain — load `hermes-cron-schedules` instead
- User is asking about Hermes hook system architecture in general — load `hermes-agent` instead

## Architecture

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

- **Brain server:** `http://100.76.149.19:5188` (Tailscale-only)
- **API key (header):** `x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85` (deployment key, safe to commit)
- **Source of truth on NAS:** `/volume2/homes/yasonok02061/mavis-brain/memories.json` (read-only client view via REST)
- **Server locked:** 515-line `mavis_brain_server.py` cannot be redeployed without disrupting the live 50+ memories → all "smart" features live client-side in `brain_smart.py`

## Client-Side Smart Layer (the reason this skill exists)

The Brain server only does CRUD + a strict LIKE-search + a per-category stats
endpoint. All the "smart" features (mem0-style behavior) live in the client
scripts because we cannot redeploy the server:

| Feature | Layer | Where |
|---|---|---|
| L2-6 TTL for context memories (>30d) | client | `brain_smart.py::compute_score()` |
| L2-7 dedup before write | client | `extract_facts.py` (char-overlap > 50%) |
| L2-8 pinned memories always on top | client | tagged in `tags[]`; `brain_smart.py` adds 1.0 to score |
| L4-14 summarization of old memories | client M3 | `brain_smart.py::summarize_old_memories()` |
| L4-15 forgetting curve (decay) | client | `brain_smart.py::compute_score()` (0.5^age/half_life) |
| L4-16 conflict detection before add | client M3 | `brain_smart.py::check_conflict()` |
| L4-13 graph (related memories) | client | `brain_smart.py::smart_search()` (tag-overlap ranking) |
| Session-end auto-extract | gateway hook | `~/.hermes/hooks/mavis-brain-auto-extract/` |

The mental model: **Brain is the database, `brain_smart.py` is the indexer
+ retrieval layer**. Treat the server as append-only log; build all
intelligence on top.

## Auto-Extraction Pipeline (the meat of the work)

```
[Conversation / Session log / stdin text]
  |
  v
extract_facts.py --text "..."  (or --from-session SID, --from-file F, --stdin)
  |
  v
[1. MiniMax M3 call with structured prompt]
  - 7 category definitions + judgement cues
  - 1-5 facts per call, importance 0-10, tags
  - Returns: JSON array (sometimes wrapped in ```json``` markdown)
  |
  v
[2. Fault-tolerant JSON parse]
  - Try ```json block``` -> bare array -> first non-empty line
  - Validate schema (fact length, category, importance range)
  |
  v
[3. Client-side dedup]
  - list_recent_memories(50) to get candidates
  - For each candidate same category, char-overlap > 50% -> skip
  |
  v
[4. add_memory to Brain]
  - category, tags, importance, source_url, is_context
  - importance goes in metadata (server bug: importance column not populated)
  - tags including "meta" / "summarized" / "pinned" carry semantic meaning
  |
  v
[5. Best-effort log_evolution to /brain/evolve]
  - For analytics only; failure here doesn't block the write
```

## Auto-Sync at Session End (gateway hook pattern)

The auto-sync lives in a **gateway hook** at `~/.hermes/hooks/mavis-brain-auto-extract/`,
NOT a shell hook in config.yaml. Why: gateway hooks fire from Telegram /
Open WebUI / API server, while shell hooks fire on command interception.
For "after a session ends, extract facts" you need gateway hooks. The
event name is **`agent:end`** (NOT `on_session_end` — that's shell-hook
namespace). See `references/gateway-hooks-guide.md` for the full
System-A vs System-B breakdown.

```yaml
# ~/.hermes/hooks/mavis-brain-auto-extract/HOOK.yaml
name: mavis-brain-auto-extract
description: "Session-end hook that auto-extracts memorable facts from each Hermes session and syncs them to Mavis Brain."
events:
  - agent:end
```

```python
# handler.py
async def handle(event_type, context):
    if event_type != "agent:end":
        return
    session_id = context.get("session_id")
    # subprocess.run([python3, extract_facts.py, --from-session, session_id])
```

After creating, restart gateway: `hermes gateway restart`.
Test: send a Telegram message, then tail
`~/.hermes/logs/hooks/mavis-brain-auto-extract.log`. **Caveat**: gateway
hooks do NOT fire from `hermes chat` (CLI) — only from gateway-routed
sessions.

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
# → {"total_memories": 55, "by_category": {...}, "by_source": {...}}
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

| Category | Purpose | Weight | Half-life (days) |
|----------|---------|--------|------------------|
| `preference` | Preferences, habits, tastes | **3.0** (highest) | 365 |
| `habit` | Daily behaviors, tool choices | 2.5 | 180 |
| `skill` | Skills, professional abilities | 2.0 | 365 |
| `workflow` | How tasks are done, project operations | 2.0 | 180 |
| `interest` | Interests, learning directions | 1.8 | 90 |
| `fact` | Objective facts, settings, identity | 1.5 | 60 |
| `context` | Situation, background | 1.5 | **30 (auto-expire)** |

Half-life values live in `brain_smart.py::HALF_LIFE_DAYS`. The decay is
`0.5 ** (age_days / half_life)` — at half_life, score is 0.5; at 2x
half_life, 0.25; etc. Adjust for your use case.

Prefer `preference` and `habit` for things the user **wants you to remember next time**. Use `fact` only for stable identity/config. Use `context` only for **durable one-off events** (the 30-day TTL will garbage-collect them).

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
6. End of a non-trivial session: run `extract_facts.py --from-session SID` to distill

Do NOT add:
- Trivia that won't matter next time
- Anything already in Brain (the extractor will dedup via char-overlap)
- Test data with `category=test` (clean it up after)

## Auto-Recall Rules (when to search Brain)

Search Brain automatically when:
- **Starting a new task** — check for related skills/workflows
- **Writing a response** — pull user preferences to match style
- **Making a decision** — check for past patterns / errors
- **User asks "do you remember..."** — explicit recall trigger
- **User references past work** ("the SEO project", "the aquarium site")

Use `sync.sh recall "context" 5` for smart-ranked dual-path search, or
`brain_smart.py smart_search` directly for the ranked JSON.

## Hermes-Specific Integration Patterns

### Pattern 1: Session-start sync
At the start of every Hermes session, call `brain/relevant` with a context summarizing the user's likely intent. Inject top results into the agent's system context as `[from Mavis Brain]` prefixed notes. Do not surface the raw API to the user.

### Pattern 2: Session-end commit (now automated)
Install the gateway hook at `~/.hermes/hooks/mavis-brain-auto-extract/`.
On every `agent:end` event, it runs `extract_facts.py --from-session SID`
which M3-distills durable facts and writes them to Brain. No manual
trigger needed for Telegram / Open WebUI sessions.

### Pattern 3: Per-message preference check
For the first message of a session, run a single `brain/relevant` query like `context: "user preferences communication style"` and use the result to shape tone. Do not call Brain for every message — it adds latency.

### Pattern 4: Avoid the local-only trap
`~/.hermes/memories/` is **per-device**. It does NOT sync. Anything you write there dies when the user switches devices. Brain is the only place that survives across Tailscale-connected devices. Default to Brain for anything cross-device; use `~/.hermes/memories/` only for environment-specific state (e.g., this device's local CLI quirks).

### Pattern 5: Weekly review (the new pattern, 2026-06)
Install the cron wrapper at `~/.hermes/scripts/brain-weekly-review.sh`,
register with `hermes cron create "0 23 * * 0" --name brain-weekly-review
--deliver "telegram:7825900351" --script brain-weekly-review.sh --no-agent`.
It runs every Sunday 23:00, calls `sync.sh brain-stats` + `sync.sh decay 90`,
and sends a Telegram summary. This catches memory decay + dedup drift
+ importance miscalibration that would otherwise go unnoticed.

## Common Pitfalls

### Pitfall 1 — Treating `~/.hermes/memories/` as shared memory
It is **not**. It's a per-device local file. Use Brain.

### Pitfall 2 — Posting secrets into Brain content
Brain is on a NAS behind Tailscale, not encrypted-at-rest by default. Do not write API keys, passwords, or tokens into `content`. The user has already made this mistake once in this session (Telegram bot token pasted into chat). Don't repeat it for them.

### Pitfall 2b — `sync.sh pull` does NOT return strict newest-first
`brain/search` with an empty `query` returns memories ranked by relevance + recency, not pure timestamp order. Use `stats` (compare `total_memories` before/after) or `search` with a unique tag to confirm a write.

### Pitfall 2c — Don't write a new `MemoryProvider` plugin in-tree
Per Hermes policy: no new in-tree memory providers. New backends must ship as standalone plugin repos. The pragmatic path is a Hermes **skill + shell script** (the one in `scripts/sync.sh`), not a core plugin.

### Pitfall 3 — Brain unreachable → silent fallback
If the Brain health check (`curl http://100.76.149.19:5188/`) times out or returns non-200, **say so**. Do not pretend to remember things; degrade to `~/.hermes/memories/` and tell the user Brain is offline. Common causes: Tailscale disconnected, NAS powered off, API key rotated.

### Pitfall 4 — Adding too much, diluting signal
50 memories is a healthy size. Each new memory must be **non-obvious and durable**. "User asked about X today" is not a memory — that's a session log. Reserve Brain for things the user will want you to know next month.

### Pitfall 5 — Synonym group miss
If you search with a term Brain doesn't have a synonym for, results will be empty. When `brain/relevant` returns 0 hits, try a broader or canonical term from the synonym groups. If still empty, the memory really doesn't exist — don't fabricate.

### Pitfall 6 — Conflicting `hermes config set` semantics
The Brain integration is **outside** Hermes's config system. Don't try to wire it via `hermes config set`. Use a separate script or hook that calls the Brain REST API directly.

### Pitfall 7 — Telegram bot session ≠ Brain session
A Telegram chat in Hermes uses a different `session_id` from Brain. The user asked about this: "Will Telegram know what we discussed here?" Answer: **no, sessions are isolated** — but **memories stored in Brain are shared**. Use the gateway hook to commit learnings to Brain at the end of every Telegram session.

### Pitfall 8 — Confusing gateway hooks and shell hooks (CRITICAL, June 2026)
Hermes has **two independent hook systems** with different event namespaces
and different firing contexts. The auto-sync hook MUST be a gateway hook
(`agent:end` event), NOT a shell hook (`on_session_end` event). The
gateway log will say "Loaded hook X for events: [agent:end]" but
the hook silently does NOT fire from `hermes chat` (CLI) — only from
gateway-routed sessions (Telegram, Open WebUI, API server, cron). See
`references/gateway-hooks-guide.md` for the full breakdown.

### Pitfall 9 — The 4 server-side bugs (CRITICAL, June 2026)
The Brain server's FastAPI route order causes 4 broken endpoints:
`/memory/entity/{a}/{b}`, `/sync/pull`, `/sync/push` all 404 because
`/memory/{memory_id}` matches first. Also: `importance` column exists
in schema but `/memory/add` does NOT insert it. Also: server has no
`/memory/list` endpoint. Also: search uses strict LIKE %term% substring
matching. See `references/brain-server-bugs.md` for workarounds
(empty-query search as "list all", metadata.importance as no-op for
future-compat, dual-path search to compensate for strict LIKE).

### Pitfall 10 — `hermes cron create --script` takes a basename, not a path
When registering `brain-weekly-review.sh` (or any cron), use
`--script brain-weekly-review.sh` (basename, resolved against
`~/.hermes/scripts/`). Passing an absolute or `~/...`-relative path
errors with "Script path must be relative to ~/.hermes/scripts/". The
script MUST be at that location.

### Pitfall 11 — `extract_facts.py` and `brain_smart.py` use `~/.hermes/.env` not just env vars
Both scripts call `os.environ.get("MINIMAX_API_KEY")` first, then fall
back to reading `~/.hermes/.env`. If you run the script in a context
where env vars are scrubbed (cron, sudo, fresh shells), the .env
fallback ensures it still works. Do NOT hardcode the key in the
script.

### Pitfall 12 — Bash `$() || ...` in pipefail mode can be fragile
When writing cron wrappers or `sync.sh`-style scripts that combine
`$(...)` command substitution with `||` fallback and a `hermes send`
pipe, prefer:
```bash
MSG_FILE=$(mktemp)
printf '%s' "$MSG" > "$MSG_FILE"
hermes send -t "telegram:$TELEGRAM_CHAT" -f "$MSG_FILE" 2>/dev/null || echo "[...] skipped"
rm -f "$MSG_FILE"
```
Do NOT use `set -euo pipefail` together with `$(...) || echo` —
the interaction can cause cryptic syntax errors at runtime (the
parser pushes the error to a later line). Build messages via temp
files instead of multi-line quoted strings with embedded `()`.

### Pitfall 13 — Two skills with the same name in different paths
There may be a class-level master at
`autonomous-ai-agents/mavis-brain-integration/` and a working copy at
`mavis-brain-integration/` (bare, no category). The active profile
resolves the bare one. If `skill_manage` says "not found in active
profile", you may be editing the wrong copy. **The bare
`mavis-brain-integration/` is the live one to update**; treat the
`autonomous-ai-agents/` one as read-only reference unless told
otherwise. The curator will consolidate them at scale.

## Verification Checklist

After wiring Hermes to Brain, verify:

- [ ] Health check responds within 1s from the active device: `curl -s http://100.76.149.19:5188/`
- [ ] `brain/stats` shows the expected memory count (compare to last known)
- [ ] Test add: write a sentinel memory with a unique tag, search for it, confirm presence
- [ ] Test semantic: query with a synonym-group term, confirm the canonical match comes back
- [ ] Test M3 extraction: `python3 extract_facts.py --text "我喜歡拉麵" --dry-run` returns a valid fact
- [ ] Test smart rank: `python3 brain_smart.py search "ETF"` returns score-sorted results
- [ ] Test gateway hook: send a Telegram message, then `tail ~/.hermes/logs/hooks/mavis-brain-auto-extract.log`
- [ ] Test cleanup: delete the sentinel, confirm `total_memories` decremented

## One-Shot Recipes

### Bootstrap: check Brain is healthy and report stats
```bash
curl -s -m 5 http://100.76.149.19:5188/ && \
curl -s http://100.76.149.19:5188/brain/stats \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
```

### Smart rank any query
```bash
python3 ~/.hermes/skills/mavis-brain-integration/scripts/brain_smart.py \
  search "你想找的東西" 10
```

### Weekly review (manual trigger, not waiting for cron)
```bash
bash ~/.hermes/scripts/brain-weekly-review.sh
```

### Distill the current session into facts
```bash
# Find the latest session id
ls -t ~/.hermes/sessions/ | head -1
# Then
python3 ~/.hermes/skills/mavis-brain-integration/scripts/extract_facts.py \
  --from-session 20260607_235248_7e735f --dry-run
```

### Bulk-import: dump Brain to a local JSON for offline review
```bash
python3 ~/.hermes/skills/mavis-brain-integration/scripts/brain_smart.py \
  list --limit 200 > /tmp/brain-dump-$(date +%Y%m%d).txt
```

### Cross-device smoke test
1. From MacBook, add a memory with `device_id=ryans-macbook-pro`
2. From another Tailscale device, run the bootstrap recipe above and confirm `total_memories` increased
3. From the second device, search for the new memory's content — should appear

## References

- `~/Desktop/mavis-brain-user-guide.md` — user-authored Brain operations guide
- `~/.minimax/skills/mavis-brain/SKILL.md` — Mavis's own integration skill (read for reference, not auto-applicable to Hermes)
- `~/.minimax/skills/mavis-brain/CROSS-DEVICE-SETUP.md` — Tailscale + multi-device setup
- `~/.minimax/scripts/mavis-brain-client.py` — reference Python client
- `~/.minimax/scratchpads/*/workspace/mavis_brain_server.py` — Brain server source (FastAPI, SQLite) — READ-ONLY, the actual NAS server cannot be redeployed
- `references/m3-extraction-patterns.md` — M3 prompt design + JSON parsing patterns (3-level fault tolerance, importance calibration)
- `references/gateway-hooks-guide.md` — full gateway-vs-shell hook comparison, event names, debugging
- `references/brain-server-bugs.md` — the 4 server-side bugs (route conflict, importance not inserted, no list endpoint, strict search) + client workarounds
- `references/nas-tailscale-setup.md` — Tailscale topology, SSH access, failure modes
- `references/hermes-integration-recipe.md` — concrete Hermes-side wiring cookbook (session-start/end hooks, failure modes, smoke test)
- `scripts/extract_facts.py` — M3-distill a conversation / session log into structured facts, client-side dedup, write to Brain
- `scripts/brain_smart.py` — client-side smart layer: forgetting curve, TTL, pinned, recall, summarize, conflict
- `scripts/brain-weekly-review.sh` — Sunday cron wrapper that posts stats + decay to Telegram
- `scripts/sync.sh` — bash wrapper exposing all Brain subcommands (`stats`, `pull`, `add`, `search`, `relevant`, `recall`, `brain-stats`, `decay`, `summarize`, `conflict`, `extract*`, `delete`)
- `scripts/verify_brain.py` — health check + smoke test for a new Brain deployment
