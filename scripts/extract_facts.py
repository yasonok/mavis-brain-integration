#!/usr/bin/env python3
"""
extract_facts.py - From a conversation/text, distill durable facts and write to Mavis Brain.

Pipeline:
  1. Receive text (or session log)
  2. Call MiniMax M3 to extract 1-5 structured facts
  3. Each fact auto-categorized + importance-rated (0-10) + tagged
  4. Client-side dedup: char-overlap > 50% in same category -> skip
  5. Write to Brain via /memory/add with metadata.importance

Key design points:
- M3 prompt has explicit category definitions + judgement rubrics (see references/m3-extraction-patterns.md)
- JSON extraction is fault-tolerant: ```json``` markdown -> first brace-delimited object -> fall through
- Server schema has `importance` column (DEFAULT 0.5) but server's /memory/add does NOT insert it;
  client passes it via metadata (also a no-op server-side) -- a future server upgrade can read it
- Client-side dedup uses list_recent_memories() (50 most recent) because server /memory/search is too strict

Usage:
  python3 extract_facts.py --text "..." | --from-session SID | --from-file F | --stdin
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# === Brain client (內嵌, 不依賴外部檔案) ===
BRAIN_URL = "http://100.76.149.19:5188"
API_KEY = "0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
USER_ID = "jason"
DEVICE_ID = "ryans-macbook-pro"

# === L4-16 conflict detection 設定 ===
# 啟用後, 每個 fact add 前先 M3 比對同 category 90 天內記憶
CONFLICT_CHECK_ENABLED = True
CONFLICT_RECENT_DAYS = 90


def brain_request(path, method="GET", data=None):
    """Direct Brain API call. Returns parsed JSON."""
    url = f"{BRAIN_URL}{path}"
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def search_memory(query, limit=5, user_id=None, category=None):
    """Search Brain. Used by L2-7 dedup + L3-9 recall + L4-16 conflict detection."""
    payload = {"query": query, "user_id": user_id or USER_ID, "limit": limit}
    if category:
        payload["category"] = category
    return brain_request("/memory/search", "POST", payload)


def list_recent_memories(user_id=None, limit=50, since=None):
    """List most recent memories. Workaround: server has no /memory/list endpoint."""
    return search_memory(query="", user_id=user_id, limit=limit)


def add_memory(content, category="fact", tags=None, memory_type="learned",
               source="hermes-m3-extract", importance=0.5, source_url=None,
               is_context=False, metadata=None):
    """Write a memory to Brain. importance goes in metadata; server schema
    has an importance column but its INSERT doesn't populate it -- this is
    a known server bug (see references/brain-server-bugs.md)."""
    payload = {
        "content": content,
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "category": category,
        "memory_type": memory_type,
        "tags": tags or [],
        "source": source,
        "metadata": {
            "importance": importance,
            "is_context": is_context,
            **(metadata or {}),
        },
    }
    if source_url:
        payload["metadata"]["source_url"] = source_url
    return brain_request("/memory/add", "POST", payload)


def log_evolution(event_type, trigger, success=True, metadata=None):
    """Log evolution event. /brain/evolve works; only /memory/* and /sync/* have route conflicts."""
    return brain_request("/brain/evolve", "POST", {
        "event_type": event_type,
        "trigger": trigger,
        "success": success,
        "device_id": DEVICE_ID,
        "metadata": metadata or {},
    })


# === MiniMax M3 client ===
def extract_with_m3(text: str) -> list:
    """Use MiniMax M3 to distill structured facts from text."""
    prompt = f"""你是 Jason 的「個人記憶蒸餾器」。從以下對話/文字抽出**真正值得長期記住**的事實 (不要日常廢話)。

【分類定義 — 嚴格遵守】
- **preference** (偏好): Jason 喜歡/討厭/習慣的東西, 例 "Jason 偏好簡潔 IDE"
- **workflow** (工作流): Jason 怎麼做事的 SOP, 例 "Jason 每天 09:00 跑 cron 寫 SEO 文章"
- **fact** (事實): 客觀事實, 例 "Cursor 1.5 處理大檔會閃退"
- **skill** (技術技能/工具用法): Jason 會用某個工具/技術, 例 "Jason 會用 Vercel 部署 Next.js"
- **interest** (興趣): Jason 對什麼有興趣, 例 "Jason 對量化交易有興趣"
- **habit** (習慣): Jason 的日常習慣, 例 "Jason 習慣用繁中溝通"
- **context** (情境): 一次性事件或當下情況, 例 "Jason 今天測試 6/7 session-end hook"

**判斷重點**:
- "我喜歡 X" -> preference
- "我平常都這樣做" -> workflow
- "X 是 Y" (客觀) -> fact
- "我會用 X" / "我知道 X 怎麼用" -> skill
- "我對 X 很有興趣" -> interest
- "我習慣 / 我都..." -> habit
- "今天/昨天/剛剛 X" -> context

【規則】
- 1-5 個事實, 沒值得記的就回傳空陣列
- 每個事實一句話 (10-30 字)
- importance: 0-10, 10 = 極重要 (例如安全問題、密碼), 0 = 雜事
- tags: 1-3 個關鍵字 (中文 or 英文)
- 如果對話提到特定工具/網站/裝置, 加 source_url (URL 或 工具名)
- 如果是 一次性 context, 標 is_context: true

【回傳格式】嚴格 JSON array, 不要其他文字:
[
  {{
    "fact": "...",
    "category": "...",
    "importance": N,
    "tags": ["..."],
    "source_url": "https://... (optional)",
    "is_context": false
  }}
]

【對話/文字】
{text[:3000]}

JSON:"""

    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            env = dict(re.findall(r"^(\w+)=(.+)$", open(env_path).read(), re.MULTILINE))
            api_key = env.get("MINIMAX_API_KEY")

    body = json.dumps({
        "model": "MiniMax-M3",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.minimax.io/anthropic/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            rdata = json.loads(resp.read())
    except Exception as e:
        print(f"  ❌ M3 call failed: {e}", file=sys.stderr)
        return []

    content = ""
    for c in rdata.get("content", []):
        content += c.get("text", "")

    # Fault-tolerant JSON extraction
    json_str = None
    m1 = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
    if m1:
        json_str = m1.group(1)
    else:
        m2 = re.search(r'\[.*?\]', content, re.DOTALL)
        if m2:
            json_str = m2.group(0)

    if not json_str:
        print(f"  [debug] M3 raw (first 500): {content[:500]}", file=sys.stderr)
        return []

    try:
        facts = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"  [debug] JSON decode error: {e}", file=sys.stderr)
        return []

    valid = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        fact = f.get("fact", "").strip()
        if not fact or len(fact) > 200:
            continue
        valid.append({
            "fact": fact,
            "category": f.get("category", "fact"),
            "importance": max(0, min(10, int(f.get("importance", 5)))),
            "tags": f.get("tags", [])[:5],
            "source_url": f.get("source_url"),
            "is_context": bool(f.get("is_context", False)),
        })
    return valid


def read_session_log(session_id: str) -> str:
    """Read a Hermes session log from ~/.hermes/sessions/."""
    sessions_dir = Path(os.path.expanduser("~/.hermes/sessions"))
    matches = list(sessions_dir.glob(f"*{session_id}*"))
    if not matches:
        return ""
    p = matches[0]
    if p.suffix == ".jsonl":
        text = p.read_text(errors="ignore")
    else:
        try:
            data = json.loads(p.read_text(errors="ignore"))
            text = json.dumps(data, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = p.read_text(errors="ignore")
    return text[:20000]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", help="raw text to extract from")
    p.add_argument("--from-session", help="Hermes session id to extract from")
    p.add_argument("--from-file", help="path to a text/json file")
    p.add_argument("--stdin", action="store_true", help="read text from stdin")
    p.add_argument("--dry-run", action="store_true", help="extract but don't write")
    args = p.parse_args()

    if args.text:
        text = args.text
    elif args.from_session:
        text = read_session_log(args.from_session)
        if not text:
            print(f"❌ Session log not found: {args.from_session}")
            sys.exit(1)
    elif args.from_file:
        text = Path(args.from_file).read_text()
    elif args.stdin:
        text = sys.stdin.read()
    else:
        print("usage: extract_facts.py --text '...' | --from-session SID | --from-file F | --stdin")
        sys.exit(1)

    print(f"→ Calling MiniMax M3 to extract facts from {len(text)} chars...")
    facts = extract_with_m3(text)

    if not facts:
        print("📝 No facts extracted.")
        return

    print(f"📝 Extracted {len(facts)} fact(s):")
    for i, f in enumerate(facts, 1):
        ctx = " [CONTEXT]" if f.get("is_context") else ""
        print(f"  [{i}] ({f['category']}, importance={f['importance']}){ctx} {f['fact']}")
        if f.get("source_url"):
            print(f"      source: {f['source_url']}")

    if args.dry_run:
        print("\n(dry-run: not writing to Brain)")
        return

    # L2-7 client-side dedup using list_recent_memories
    print("\n→ Writing to Brain (with client-side dedup)...")
    written = 0
    skipped = 0
    try:
        candidates = list_recent_memories(limit=50).get("results", [])
    except Exception:
        candidates = []

    for f in facts:
        try:
            dup = False
            for e in candidates:
                if e.get("category") != f["category"]:
                    continue
                e_content = e.get("content", "")
                if not e_content:
                    continue
                overlap = len(set(f["fact"]) & set(e_content)) / max(len(f["fact"]), len(e_content), 1)
                if overlap > 0.5:
                    dup = True
                    break
            if dup:
                skipped += 1
                print(f"  ⏭️  跳過重複: {f['fact'][:60]}")
                continue

            # L4-16 conflict detection (可關閉)
            if CONFLICT_CHECK_ENABLED and f["importance"] >= 6:
                try:
                    # 動態 import 避免 cycle
                    sys.path.insert(0, str(Path(__file__).parent))
                    import brain_smart
                    conflict_result = brain_smart.check_conflict(
                        f["fact"], f["category"], recent_days=CONFLICT_RECENT_DAYS
                    )
                    if conflict_result.get("conflict"):
                        print(f"  ⚠️  衝突偵測 (阻擋 importance={f['importance']}): {f['fact'][:60]}")
                        print(f"     reason: {conflict_result.get('reason', '?')}")
                        if conflict_result.get("existing_id"):
                            print(f"     existing: {conflict_result['existing_id']}")
                        skipped += 1
                        continue
                except Exception as e:
                    # conflict check 失敗不阻擋 add
                    pass

            result = add_memory(
                content=f["fact"],
                category=f["category"],
                tags=f["tags"],
                importance=f["importance"],
                source_url=f.get("source_url"),
                is_context=f.get("is_context", False),
            )
            if "error" not in result:
                written += 1
                print(f"  ✅ {f['fact'][:60]}")
            else:
                print(f"  ⚠️  {result.get('error', '?')}: {f['fact'][:60]}")
        except Exception as e:
            print(f"  ❌ {e}: {f['fact'][:60]}")

    try:
        log_evolution(
            "facts_extracted",
            "extract_facts.py",
            success=written > 0,
            metadata={"extracted": len(facts), "written": written, "skipped": skipped},
        )
    except Exception:
        pass

    print(f"\n✅ Done. {written}/{len(facts)} facts written ({skipped} duplicates skipped).")


if __name__ == "__main__":
    main()
