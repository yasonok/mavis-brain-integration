#!/usr/bin/env python3
"""
extract_facts.py - 從對話/文字自動提煉值得記住的事實, 寫入 Mavis Brain

Pipeline:
  1. 接收對話文字 (或 session log)
  2. 呼叫 MiniMax M3 蒸餾出 1-5 個事實
  3. 每個 fact 自動分類 + 評 importance (0-10)
  4. 透過 Brain client 寫入 (去重由 server 端做)
  5. 進化 log 給 Brain server 追蹤

Usage:
  python3 extract_facts.py --text "我今天發現 Cursor 1.5 有 bug"
  python3 extract_facts.py --from-session 20260607_041912_d69618
  python3 extract_facts.py --from-file /path/to/conversation.txt
  python3 extract_facts.py --stdin  < conversation.txt
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

def brain_request(path, method="GET", data=None):
    """直接打 Brain API"""
    url = f"{BRAIN_URL}{path}"
    headers = {"Content-Type": "application/json", "x-api-key": API_KEY}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())

def add_memory(content, category="fact", tags=None, memory_type="learned"):
    """新增記憶到 Brain"""
    return brain_request("/memory/add", "POST", {
        "content": content,
        "user_id": USER_ID,
        "device_id": DEVICE_ID,
        "category": category,
        "memory_type": memory_type,
        "tags": tags or [],
    })

def log_evolution(event_type, trigger, success=True, metadata=None):
    """記進化事件"""
    return brain_request("/brain/evolve", "POST", {
        "event_type": event_type,
        "trigger": trigger,
        "success": success,
        "device_id": DEVICE_ID,
        "metadata": metadata or {},
    })

# === MiniMax M3 client ===
def extract_with_m3(text: str) -> list:
    """用 MiniMax M3 從 text 蒸餾出結構化事實

    回傳 list of dict: [{"fact": str, "category": str, "importance": int, "tags": list}]
    """
    prompt = f"""你是 Jason 的「個人記憶蒸餾器」。從以下對話/文字抽出**真正值得長期記住**的事實 (不要日常廢話)。

【規則】
- 1-5 個事實, 沒值得記的就回傳空陣列
- 每個事實一句話 (10-30 字)
- 分類: preference (偏好) | workflow (工作流) | fact (事實) | skill (技能) | interest (興趣) | habit (習慣) | context (情境)
- importance: 0-10, 10 = 極重要 (例如安全問題、密碼), 0 = 雜事
- tags: 1-3 個關鍵字 (中文 or 英文)

【回傳格式】嚴格 JSON array, 不要其他文字:
[{{"fact": "...", "category": "...", "importance": N, "tags": ["..."]}}]

【對話/文字】
{text[:3000]}

JSON:"""

    payload = {
        "model": "MiniMax-M3",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }

    req = urllib.request.Request(
        "https://api.minimax.io/anthropic/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": "*** not used, we use Authorization Bearer below",
        },
        method="POST",
    )
    # 改用 Authorization Bearer (M3 用的是 OpenAI-style 認證)
    req = urllib.request.Request(
        "https://api.minimax.io/anthropic/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    # 讀 MiniMax API key
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        env_path = Path.home() / ".hermes" / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                m = re.match(r'^MINIMAX_API_KEY=(.+)$', line)
                if m:
                    api_key = m.group(1).strip()
                    break
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY not found in env or ~/.hermes/.env")
    req.add_header("Authorization", f"Bearer {api_key}")

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())

    # 抓 M3 回的文字
    content = ""
    for c in result.get("content", []):
        if c.get("type") == "text":
            content += c.get("text", "")

    # 抓 JSON 區塊（容錯 markdown ```json``` 包裹、單/雙引號）
    # 1. 先找 ```json ... ``` 區塊
    m = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
    if not m:
        # 2. 找裸 JSON 陣列（greedy, 抓最長可能的）
        m = re.search(r'\[[\s\S]*\]', content)
    if not m:
        return []
    json_text = m.group(1) if m.lastindex else m.group(0)
    try:
        facts = json.loads(json_text)
        # 驗證 schema
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
            })
        return valid
    except json.JSONDecodeError:
        return []

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text", help="直接餵一段文字")
    p.add_argument("--from-file", help="從檔案讀")
    p.add_argument("--stdin", action="store_true", help="從 stdin 讀")
    p.add_argument("--from-session", help="從 hermes session DB 讀 (session_id)")
    p.add_argument("--dry-run", action="store_true", help="只顯示事實不寫入")
    args = p.parse_args()

    # 1. 收集文字
    text = ""
    if args.text:
        text = args.text
    elif args.from_file:
        text = Path(args.from_file).read_text()
    elif args.stdin:
        text = sys.stdin.read()
    elif args.from_session:
        # 從 hermes session DB 抓
        db = Path.home() / ".hermes" / "sessions" / f"{args.from_session}.jsonl"
        if not db.exists():
            # 找實際檔
            sess_dir = Path.home() / ".hermes" / "sessions"
            candidates = list(sess_dir.glob(f"*{args.from_session}*"))
            if not candidates:
                print(f"❌ session not found: {args.from_session}", file=sys.stderr)
                sys.exit(1)
            db = candidates[0]
        text = db.read_text()
    else:
        p.print_help()
        sys.exit(1)

    if not text.strip():
        print("❌ empty text", file=sys.stderr)
        sys.exit(1)

    # 2. M3 蒸餾
    print(f"→ Calling MiniMax M3 to extract facts from {len(text)} chars...")
    try:
        facts = extract_with_m3(text)
    except Exception as e:
        print(f"❌ M3 extraction failed: {e}", file=sys.stderr)
        log_evolution("extraction_error", "extract_facts.py", success=False, metadata={"error": str(e)})
        sys.exit(2)

    if not facts:
        print("✅ No memorable facts found in this text.")
        return

    print(f"📝 Extracted {len(facts)} fact(s):")
    for i, f in enumerate(facts, 1):
        print(f"  [{i}] ({f['category']}, importance={f['importance']}) {f['fact']}")
        if f['tags']:
            print(f"      tags: {f['tags']}")

    if args.dry_run:
        print("\n(dry-run: not writing to Brain)")
        return

    # 3. 寫入 Brain
    print("\n→ Writing to Brain...")
    written = 0
    for f in facts:
        try:
            result = add_memory(
                content=f["fact"],
                category=f["category"],
                tags=f["tags"],
            )
            if "error" not in result:
                written += 1
                print(f"  ✅ {f['fact'][:60]}")
            else:
                print(f"  ⚠️  {result.get('error', '?')}: {f['fact'][:60]}")
        except Exception as e:
            print(f"  ❌ {e}: {f['fact'][:60]}")

    # 4. 進化 log (best-effort, 失敗不影響主流程)
    try:
        log_evolution(
            "facts_extracted",
            "extract_facts.py",
            success=written > 0,
            metadata={"extracted": len(facts), "written": written, "source_len": len(text)},
        )
    except Exception as e:
        print(f"  ⚠️  evolution log skipped: {e}")

    print(f"\n✅ Done. {written}/{len(facts)} facts written to Brain.")

if __name__ == "__main__":
    main()
