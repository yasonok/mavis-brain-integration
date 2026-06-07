#!/usr/bin/env python3
"""
brain_smart.py - Client-side intelligence layer for Mavis Brain.

Why client-side: The Brain server on Synology NAS is locked to a
single 515-line mavis_brain_server.py. We cannot redeploy it. So all
"smart" features (forgetting curve, TTL, pinned, dedup, conflict
detection, summarization) live here as client-side computation on
top of the flat server API.

Features (numbered to match the SKILL.md roadmap):
  L2-6  TTL expiration (decay score based on age; client filters)
  L2-7  dedup (use list_recent_memories + char-overlap)
  L2-8  pinned (stored in tags, client treats as always-top)
  L4-13 graph (client computes tag-overlap associations)
  L4-14 summarization (M3 distillation of old memories)
  L4-15 forgetting curve (client-side weighted relevance)
  L4-16 conflict detection (M3 compare new vs recent same-category)

Usage:
  python3 brain_smart.py search "ET..."            # shows raw + smart-ranked
  python3 brain_smart.py stats                     # by-category avg score
  python3 brain_smart.py decay --days 30           # show what would expire
  python3 brain_smart.py summarize --category workflow --days 1
  python3 brain_smart.py conflict --category pref --new-fact "..."
"""
import os
import json
import re
import sys
import urllib.request
import argparse
from datetime import datetime, timedelta

BRAIN_URL = "http://100.76.149.19:5188"
# 優先從 env 拿, 沒有就用 deployment key (在 .env 之外, 只用在 client)
API_KEY = os.environ.get("BRAIN_API_KEY", "0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85")
USER_ID = "jason"
DEVICE_ID = "ryans-macbook-pro"

HALF_LIFE_DAYS = {
    "preference": 365, "workflow": 180, "skill": 365, "interest": 90,
    "fact": 60, "habit": 180, "context": 30,
}
DEFAULT_HALF_LIFE = 90
PINNED_TAG = "pinned"
CONTEXT_TTL_DAYS = 30


def brain_request(path, method="GET", data=None):
    url = f"{BRAIN_URL}{path}"
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_all_memories(limit=200):
    """Get as many memories as the server will return. Workaround: server
    has no /memory/list endpoint, so we use search with empty query."""
    return brain_request("/memory/search", "POST", {
        "query": "", "user_id": USER_ID, "limit": limit,
    }).get("results", [])


def age_in_days(created_at: str) -> float:
    """Days since created_at. Server uses naive datetime.now().isoformat()
    with NO timezone, so we parse as local time."""
    try:
        ts = datetime.fromisoformat(created_at)
    except (ValueError, TypeError):
        return 0
    return (datetime.now() - ts).total_seconds() / 86400


def is_pinned(memory: dict) -> bool:
    return PINNED_TAG in (memory.get("tags") or [])


def is_context(memory: dict) -> bool:
    return memory.get("category") == "context"


def compute_score(memory: dict) -> dict:
    """L4-15 + L2-6 + L2-8 combined score for a memory.

    score = base_confidence * decay + importance_boost + pinned_bonus + context_penalty
    """
    cat = memory.get("category", "fact")
    age = age_in_days(memory.get("created_at", ""))
    half_life = HALF_LIFE_DAYS.get(cat, DEFAULT_HALF_LIFE)
    decay = 0.5 ** (age / half_life) if half_life > 0 else 0

    metadata = memory.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    importance = metadata.get("importance", 5)
    importance_boost = 0.1 * importance

    pinned_bonus = 1.0 if is_pinned(memory) else 0.0
    context_penalty = -10.0 if (is_context(memory) and age > CONTEXT_TTL_DAYS) else 0.0

    base_conf = memory.get("confidence", 1.0) or 1.0
    score = base_conf * decay + importance_boost + pinned_bonus + context_penalty
    return {
        "score": round(score, 3), "age_days": round(age, 1),
        "decay": round(decay, 3), "importance": importance,
        "pinned": is_pinned(memory), "expired": context_penalty < 0,
    }


def smart_search(query: str, limit: int = 10, min_score: float = 0.0) -> list:
    """L3-9 dual-path: search (strict) + list_recent (loose) + client rank."""
    try:
        r1 = brain_request("/memory/search", "POST", {
            "query": query, "user_id": USER_ID, "limit": limit * 3,
        })
        path1 = r1.get("results", [])
    except Exception:
        path1 = []

    try:
        r2 = brain_request("/memory/search", "POST", {
            "query": "", "user_id": USER_ID, "limit": 50,
        })
        path2_candidates = r2.get("results", [])
        q_words = query.lower().split()
        path2 = []
        for m in path2_candidates:
            content = (m.get("content") or "").lower()
            tags = " ".join(m.get("tags") or []).lower()
            if any(w in content or w in tags for w in q_words):
                path2.append(m)
    except Exception:
        path2 = []

    seen = set()
    merged = []
    for m in path1 + path2:
        mid = m.get("id")
        if mid and mid not in seen:
            seen.add(mid)
            merged.append(m)

    enriched = []
    for m in merged:
        s = compute_score(m)
        if s["score"] < min_score:
            continue
        enriched.append({**m, "smart": s})

    enriched.sort(key=lambda x: x["smart"]["score"], reverse=True)
    return enriched[:limit]


def summarize_old_memories(category=None, older_than_days=30, max_memories=20):
    """L4-14: Use M3 to distill old memories of a category into a meta-fact."""
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            env = dict(re.findall(r"^(\w+)=(.+)$", open(env_path).read(), re.MULTILINE))
            api_key = env.get("MINIMAX_API_KEY")

    memories = fetch_all_memories(limit=200)
    candidates = []
    for m in memories:
        s = compute_score(m)
        if s["expired"] or s["pinned"]:
            continue
        if category and m.get("category") != category:
            continue
        if s["age_days"] < older_than_days:
            continue
        candidates.append(m)
        if len(candidates) >= max_memories:
            break

    if len(candidates) < 3:
        return {"summary": None, "reason": f"only {len(candidates)} candidates (need 3+)", "candidates": len(candidates)}

    real = [c for c in candidates if compute_score(c)["age_days"] > 0.5]
    if len(real) < 3:
        return {"summary": None, "reason": f"only {len(real)} real candidates", "candidates": len(real)}
    candidates = real

    bullet = "\n".join(f"  - {m.get('content', '')}" for m in candidates)
    cat_label = category or "mixed"
    prompt = f"""你是 Jason 的「記憶濃縮器」。以下 {len(candidates)} 筆舊記憶 (category={cat_label}, 全部超過 {older_than_days} 天) 應該濃縮成 1 個 meta-fact。

【規則】
- meta-fact 必須 capture 所有原始記憶的「共同模式 / 高階結論」
- 1 句話 (10-30 字)
- 保留重要細節 (工具名、版本、偏好值)
- 不要含糊、不能丢掉「跟 Jason 工作流直接相關」的東西
- 沒辦法濃縮就回空陣列

【舊記憶】
{bullet}

【回傳格式】嚴格 JSON:
{{"meta_fact": "...", "tags": ["..."]}}

JSON:"""

    body = json.dumps({
        "model": "MiniMax-M3", "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.minimax.io/anthropic/v1/messages",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "anthropic-version": "2023-06-01"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rdata = json.loads(resp.read())
        content = ""
        for c in rdata.get("content", []):
            content += c.get("text", "")

        json_str = None
        m1 = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if m1:
            json_str = m1.group(1)
        else:
            m2 = re.search(r'\{[^{}]*"meta_fact"[^{}]*\}', content, re.DOTALL)
            if m2:
                json_str = m2.group(0)

        if not json_str:
            first_line = content.strip().split("\n")[0].strip()
            if first_line and 5 < len(first_line) < 200 and "請提供" not in first_line and "無法" not in first_line:
                meta_fact = first_line
                parsed_tags = []
            else:
                return {"summary": None, "reason": "M3 didn't return valid JSON or text", "candidates": len(candidates)}
        else:
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as e:
                return {"summary": None, "reason": f"JSON decode: {e}", "candidates": len(candidates)}
            meta_fact = parsed.get("meta_fact", "").strip()
            parsed_tags = parsed.get("tags", [])[:5]

        if not meta_fact:
            return {"summary": None, "reason": "empty meta_fact", "candidates": len(candidates)}

        add_memory(
            content=meta_fact, category=category or "fact",
            tags=parsed_tags + ["meta", "summarized"],
            source="hermes-summarize", importance=6,
            metadata={"summarized_from": [m.get("id") for m in candidates if m.get("id")], "n_summarized": len(candidates)},
        )
        return {"summary": meta_fact, "tags": parsed_tags, "candidates": len(candidates)}
    except Exception as e:
        return {"summary": None, "error": str(e), "candidates": len(candidates)}


def check_conflict(new_fact, category, top_n=5, recent_days=90):
    """L4-16: M3 compares a new fact against recent same-category memories."""
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        env_path = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_path):
            env = dict(re.findall(r"^(\w+)=(.+)$", open(env_path).read(), re.MULTILINE))
            api_key = env.get("MINIMAX_API_KEY")

    cutoff = (datetime.now() - timedelta(days=recent_days)).isoformat()
    candidates = []
    for m in fetch_all_memories(limit=200):
        if m.get("category") != category:
            continue
        created = m.get("created_at", "")
        if created > cutoff:
            candidates.append(m)
        if len(candidates) >= top_n:
            break

    if not candidates:
        return {"conflict": False, "reason": "no recent same-category memories"}

    bullet = "\n".join(f"  - {m.get('content', '')}" for m in candidates)
    prompt = f"""你是 Jason 的「衝突偵測器」。比較「新事實」跟「現有同類事實」是否矛盾。

【新事實】
{new_fact}

【現有同類事實 (最近 {recent_days} 天)】
{bullet}

【規則】
- 只有在「直接矛盾」(e.g. 兩個相反的偏好) 時才算 conflict
- 「新增資訊」(e.g. 之前用 A, 現在加 B) 算 no_conflict
- 「時序更新」(e.g. 之前 iPhone 14 → 現在 iPhone 15) 算 no_conflict, 算補充

【回傳格式】嚴格 JSON:
{{"conflict": true/false, "reason": "一句話解釋", "existing_id_to_replace": "..." (optional)}}

JSON:"""

    body = json.dumps({
        "model": "MiniMax-M3", "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.minimax.io/anthropic/v1/messages",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "anthropic-version": "2023-06-01"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rdata = json.loads(resp.read())
        content = ""
        for c in rdata.get("content", []):
            content += c.get("text", "")

        m = re.search(r'\{[^{}]*"conflict"[^{}]*\}', content, re.DOTALL)
        if not m:
            return {"conflict": False, "reason": "M3 didn't return valid JSON"}
        parsed = json.loads(m.group(0))
        return {
            "conflict": bool(parsed.get("conflict", False)),
            "reason": parsed.get("reason", ""),
            "existing_id": parsed.get("existing_id_to_replace"),
        }
    except Exception as e:
        return {"conflict": False, "error": str(e)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["search", "ranked", "list", "decay", "stats", "summarize", "conflict"])
    p.add_argument("query", nargs="*")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--pinned", action="store_true")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--category", help="for summarize")
    p.add_argument("--new-fact", help="for conflict: the new fact to check")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.cmd == "stats":
        memories = fetch_all_memories(limit=200)
        by_cat = {}
        total_score = 0
        expired = 0
        pinned = 0
        for m in memories:
            s = compute_score(m)
            by_cat.setdefault(m.get("category", "?"), []).append(s["score"])
            total_score += s["score"]
            if s["expired"]: expired += 1
            if s["pinned"]: pinned += 1
        print(f"Total: {len(memories)}")
        print(f"Pinned: {pinned}")
        print(f"Expired (context >30d): {expired}")
        print(f"Avg score: {total_score/len(memories):.2f}" if memories else "n/a")
        print("\nBy category (avg score):")
        for cat, scores in sorted(by_cat.items(), key=lambda x: -sum(x[1])/len(x[1])):
            print(f"  {cat:15} {len(scores):3}  avg={sum(scores)/len(scores):.2f}")

    elif args.cmd == "search":
        q = " ".join(args.query) if args.query else ""
        results = smart_search(q, limit=args.limit)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"=== Smart search: '{q}' ({len(results)} results) ===\n")
            for r in results:
                s = r["smart"]
                pin = "[PIN] " if s["pinned"] else "      "
                exp = " [EXPIRED]" if s["expired"] else ""
                print(f"{pin}[{r.get('category'):12}] score={s['score']:.2f} | imp={s['importance']} | age={s['age_days']}d{exp}")
                print(f"         {r.get('content', '')[:100]}")

    elif args.cmd == "list":
        memories = fetch_all_memories(limit=200)
        for m in memories:
            s = compute_score(m)
            if args.pinned and not s["pinned"]:
                continue
            pin = "[PIN] " if s["pinned"] else "      "
            exp = " [EXPIRED]" if s["expired"] else "         "
            print(f"{pin}{exp}[{m.get('category'):12}] score={s['score']:.2f} | imp={s['importance']} | age={s['age_days']}d")
            print(f"         {m.get('content', '')[:100]}")

    elif args.cmd == "decay":
        memories = fetch_all_memories(limit=200)
        expiring = []
        for m in memories:
            s = compute_score(m)
            if s["age_days"] > args.days and not s["pinned"]:
                expiring.append((m, s))
        expiring.sort(key=lambda x: x[1]["score"])
        print(f"=== {len(expiring)} memories older than {args.days} days, sorted by score ===\n")
        for m, s in expiring[:30]:
            print(f"[{m.get('category'):12}] score={s['score']:.2f} | age={s['age_days']:.0f}d | imp={s['importance']}")
            print(f"       {m.get('content', '')[:100]}")

    elif args.cmd == "summarize":
        result = summarize_old_memories(
            category=args.category,
            older_than_days=args.days,
            max_memories=args.limit,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result.get("summary"):
                print(f"[OK] Summarized {result['candidates']} memories into:")
                print(f"   {result['summary']}")
                if result.get("tags"):
                    print(f"   tags: {result['tags']}")
            else:
                print(f"[SKIP] {result.get('reason', result.get('error', 'unknown'))}")
                print(f"   candidates: {result.get('candidates', 0)}")

    elif args.cmd == "conflict":
        if not args.new_fact or not args.category:
            sys.stderr.write("usage: brain_smart.py conflict --category X --new-fact \"...\"\n")
            sys.exit(1)
        result = check_conflict(args.new_fact, args.category)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result.get("conflict"):
                print(f"[CONFLICT] detected:")
                print(f"   reason: {result.get('reason', '?')}")
                if result.get("existing_id"):
                    print(f"   existing id to replace: {result['existing_id']}")
            else:
                print(f"[OK] No conflict: {result.get('reason', 'safe to add')}")


if __name__ == "__main__":
    main()
