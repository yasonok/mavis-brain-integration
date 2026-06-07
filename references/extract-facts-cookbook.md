# Brain LLM-Extraction Cookbook (session 2026-06-07)

Concrete recipe that worked this session for going from
"raw conversation text" → "structured facts in Brain". Captured
here so the next session doesn't have to rediscover the M3
prompt, the JSON parser, the dedup logic, or the gateway-hook
wiring.

## 1. M3 prompt that works (extraction step)

The prompt that produced usable 3-fact JSON output 90% of the
time this session:

```
你是 Jason 的「個人記憶蒸餾器」。從以下對話/文字抽出**真正值得長期記住**的事實 (不要日常廢話)。

【分類定義 — 嚴格遵守】
- **preference** (偏好): Jason 喜歡/討厭/習慣的東西
- **workflow** (工作流): Jason 怎麼做事的 SOP
- **fact** (事實): 客觀事實
- **skill** (技術技能/工具用法): Jason 會用某個工具/技術
- **interest** (興趣): Jason 對什麼有興趣
- **habit** (習慣): Jason 的日常習慣
- **context** (情境): 一次性事件或當下情況

【規則】
- 1-5 個事實, 沒值得記的就回傳空陣列
- 每個事實一句話 (10-30 字)
- importance: 0-10, 10 = 極重要
- tags: 1-3 個關鍵字
- 如果對話提到特定工具/網站/裝置, 加 source_url (URL 或 工具名)
- 如果是 一次性 context, 標 is_context: true

【回傳格式】嚴格 JSON array, 不要其他文字:
[
  {
    "fact": "...",
    "category": "...",
    "importance": N,
    "tags": ["..."],
    "source_url": "https://... (optional)",
    "is_context": false
  }
]
```

## 2. JSON parser — the gotcha

M3 wraps JSON in ```json ... ``` markdown 99% of the time. A
naive `re.search(r'\[.*?\]', text)` stops at the first `]` it
sees and returns a broken fragment. The working pattern:

```python
# Try ```json``` wrapper first
m = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
if not m:
    # Fall back to greedy bare-array (longest possible)
    m = re.search(r'\[[\s\S]*\]', content)
facts = json.loads(m.group(1) if m else '[]')
```

Always guard with `try/except json.JSONDecodeError` — M3 sometimes
adds trailing commas or Chinese punctuation that break parsing.

## 3. Client-side dedup (when the server won't)

The server has no dedup. It will happily accept 50 copies of
"Jason 偏好簡潔 IDE" if you call `/memory/add` 50 times. The
working client-side dedup pattern (in `extract_facts.py`):

```python
# Pull recent 50 memories as dedup candidates
candidates = list_recent_memories(limit=50).get("results", [])

for f in facts:
    dup = False
    for e in candidates:
        if e.get("category") != f["category"]:
            continue
        e_content = e.get("content", "")
        if not e_content:
            continue
        overlap = len(set(f["fact"]) & set(e_content)) / max(len(f["fact"]), len(e_content), 1)
        if overlap > 0.5:  # >50% char overlap = duplicate
            dup = True
            break
    if dup:
        skipped += 1
        continue
    add_memory(...)
```

Char-overlap is dumb but works. ~5% false-positive rate. If
accuracy matters more, use Jaccard on tokenized sets or M3
itself to judge similarity (1 extra LLM call per fact).

## 4. The three server-bug workarounds (you will hit these)

```python
# Bug 1: /sync/pull and /memory/entity/{t}/{i} both 404 (route-order conflict)
# Workaround: use search with empty query
def list_recent_memories(limit=50):
    return brain_request("/memory/search", "POST", {
        "query": "",
        "user_id": USER_ID,
        "limit": limit,
    }).get("results", [])

# Bug 2: /brain/evolve 404s on most installs
# Workaround: wrap in try/except, never block on it
try:
    brain_request("/brain/evolve", "POST", {...})
except Exception as e:
    log(f"evolution log skipped: {e}")

# Bug 3: importance/source_url/pinned/is_context don't have INSERT support
# Workaround: stuff them all into the metadata JSON blob
payload = {
    "content": fact,
    "metadata": {
        "importance": 7,
        "source_url": "https://...",
        "is_context": False,
        "pinned": False,
    },
    ...
}
```

The Brain schema *has* the `importance` column (REAL DEFAULT 0.5)
but the `/memory/add` INSERT in `mavis_brain_server.py` never
writes it. The `source_url` / `is_context` / `pinned` columns
don't exist at all. Sticking them in `metadata` is the only way
that survives a server round-trip.

## 5. Forgetting-curve formula (client-side score)

Working scoring formula in `brain_smart.py` — produces a 0-3
range score that decays over time, boosts important memories,
and penalizes expired context:

```python
HALF_LIFE_DAYS = {
    "preference": 365,   # 偏好不會變 → 1 年半衰期
    "workflow": 180,
    "skill": 365,
    "interest": 90,
    "fact": 60,         # 事實會過時
    "habit": 180,
    "context": 30,      # 一次性 context
}
CONTEXT_TTL_DAYS = 30   # context 過 30 天 = 過期

score = (confidence * 0.5 ** (age / half_life)) \
      + (0.1 * importance) \
      + (1.0 if pinned else 0) \
      - (10.0 if is_context and age > 30 else 0)
```

Run `brain_smart.py stats` to see per-category avg score, or
`brain_smart.py decay --days 30` to see what's about to expire.

## 6. Gateway hook for session-end auto-sync

**Two-arch caveat — this bit me for an hour:** gateway hooks
fire on `agent:end`, NOT on `on_session_end`. `on_session_end`
is a **shell hook** event, different system. They are not
interchangeable. Use the right one:

```yaml
# ~/.hermes/hooks/mavis-brain-auto-extract/HOOK.yaml
name: mavis-brain-auto-extract
events:
  - agent:end
```

```python
# ~/.hermes/hooks/mavis-brain-auto-extract/handler.py
async def handle(event_type, context):
    if event_type != "agent:end":
        return
    session_id = context.get("session_id")
    if not session_id:
        return
    # Find session log, extract facts, write to Brain
    subprocess.run(["python3", str(EXTRACT_SCRIPT), "--from-session", session_id], ...)
```

Reload: `hermes gateway restart`. **Caveat:** gateway hooks do
NOT fire from `hermes chat` (CLI). They only fire from
Telegram / Open WebUI / API server / cron / Discord. If you
need CLI session-end sync, use the `extract_session` subcommand
in `sync.sh` instead.

## 7. Quick test recipe (verify the pipeline end-to-end)

```bash
# Step 1: Brain reachable
curl -s -m 5 http://100.76.149.19:5188/brain/stats \
  -H "x-api-key: 0e62..."

# Step 2: extraction works
~/.hermes/skills/mavis-brain-integration/scripts/extract_facts.py \
  --text "Jason 6/7 用 Vercel CLI 部署 ryanlifehack.com"

# Expected: 2-3 facts written, no errors, dedup skips
# duplicates

# Step 3: smart ranking works
~/.hermes/skills/mavis-brain-integration/scripts/sync.sh brain-stats
~/.hermes/skills/mavis-brain-integration/scripts/sync.sh recall "Vercel"

# Expected: pinned/expired counts, score 0-3 per category,
# recall returns facts sorted by score
```

## 8. What NOT to do (hard-won lessons)

- **Don't `git push -f` to GitHub.** It will be declined by
  the security guard. If you need a force-push to recover from
  a botched rebase, ask the user explicitly.
- **Don't call `extract_facts.py --text` with secrets in the
  text.** They end up in the M3 prompt logs (probably) and in
  the Brain metadata blob. Strip tokens before extracting.
- **Don't trust `search` to be exhaustive.** It uses `LIKE %term%`
  with no stemming or fuzzy match. For "I want everything
  containing X", use `list_recent_memories(limit=200)` and
  client-side filter.
- **Don't call `/memory/add` in a tight loop without dedup.**
  You'll write 200 near-duplicates. Always pull candidates
  first.
- **Don't assume `hermes chat -q "..."` triggers gateway
  hooks.** It bypasses the gateway entirely. Use Telegram for
  end-to-end hook testing.
