#!/usr/bin/env bash
# Mavis Brain sync script — Hermes ↔ Synology NAS Brain server
# Usage:
#   sync.sh stats                    # brain health + counts
#   sync.sh pull [N]                 # show N most recent memories (default 5)
#   sync.sh add "TEXT" [category]    # write a new memory
#   sync.sh extract "TEXT"           # LLM-extract facts from text, then add all
#   sync.sh extract-stdin            # read text from stdin, extract + add
#   sync.sh extract-session SESSION  # extract from hermes session log
#   sync.sh recall "CONTEXT" [N]     # L3-9: 雙路徑查詢 (search + list + smart rank)
#   sync.sh brain-stats              # L4-15: smart stats w/ forgetting curve
#   sync.sh decay [N_DAYS]           # 列出會過期的記憶
#   sync.sh search "QUERY" [N]       # keyword search
#   sync.sh relevant "CONTEXT" [N]   # semantic search (synonym-expanded)
#   sync.sh delete ID                # delete by id
#   sync.sh help                     # show this help
#
# Configuration (env vars override defaults):
#   BRAIN_URL  default: http://100.76.149.19:5188
#   API_KEY    default: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85
#   USER_ID    default: jason
#   DEVICE_ID  default: ryans-macbook-pro

set -euo pipefail

BRAIN_URL="${BRAIN_URL:-http://100.76.149.19:5188}"
API_KEY="${API_KEY:-0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85}"
USER_ID="${USER_ID:-jason}"
DEVICE_ID="${DEVICE_ID:-ryans-macbook-pro}"

# JSON-encode a string safely (no shell injection in content/queries)
jenc() { python3 -c 'import json,sys;print(json.dumps(sys.stdin.read().rstrip()))'; }

# Pretty-print a memory entry from a list
format_memories() {
  python3 -c "
import json, sys
d = json.load(sys.stdin)
results = d.get('results', d.get('memories', d if isinstance(d, list) else []))
if not results:
    print('(no memories)')
    sys.exit(0)
for m in results:
    cat = m.get('category', '?')
    src = m.get('source', '?')
    ts  = m.get('created_at', m.get('timestamp', ''))[:19]
    txt = m.get('content', '')[:140]
    mid = m.get('id', '')
    print(f'[{cat:11s}] {ts}  {txt}')
    if mid:
        print(f'            id={mid}')
"
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  stats)
    curl -s -m 10 "$BRAIN_URL/brain/stats" \
      -H "x-api-key: $API_KEY" | python3 -m json.tool
    ;;

  pull)
    n="${1:-5}"
    curl -s -m 10 -X POST "$BRAIN_URL/memory/search" \
      -H "Content-Type: application/json" \
      -H "x-api-key: $API_KEY" \
      -d "{\"query\": \"\", \"user_id\": \"$USER_ID\", \"limit\": $n}" \
      | format_memories
    echo ""
    echo "ℹ️  Note: Brain sorts by relevance+recency, NOT strict newest-first."
    echo "   Use \`sync.sh search <unique-tag>\` to confirm it was written."
    ;;

  add)
    text="${1:-}"
    category="${2:-fact}"
    if [ -z "$text" ]; then
      echo "usage: $0 add \"TEXT\" [category]" >&2
      exit 1
    fi
    encoded=$(printf '%s' "$text" | jenc)
    curl -s -m 10 -X POST "$BRAIN_URL/memory/add" \
      -H "Content-Type: application/json" \
      -H "x-api-key: $API_KEY" \
      -d "{
        \"content\": $encoded,
        \"category\": \"$category\",
        \"user_id\": \"$USER_ID\",
        \"device_id\": \"$DEVICE_ID\",
        \"source\": \"hermes\"
      }" | python3 -m json.tool
    ;;

  extract)
    text="${1:-}"
    if [ -z "$text" ]; then
      echo "usage: $0 extract \"TEXT\"  (or use extract-stdin / extract-session)" >&2
      exit 1
    fi
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/extract_facts.py" --text "$text"
    ;;

  extract-stdin)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/extract_facts.py" --stdin
    ;;

  extract-session)
    session="${1:-}"
    if [ -z "$session" ]; then
      echo "usage: $0 extract-session SESSION_ID" >&2
      exit 1
    fi
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/extract_facts.py" --from-session "$session"
    ;;

  summarize)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/brain_smart.py" summarize \
      --category "${1:-workflow}" --days "${2:-7}" --limit "${3:-10}"
    ;;

  conflict)
    category="${1:-}"
    new_fact="${2:-}"
    if [ -z "$category" ] || [ -z "$new_fact" ]; then
      echo "usage: $0 conflict CATEGORY \"NEW FACT\"" >&2
      exit 1
    fi
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/brain_smart.py" conflict \
      --category "$category" --new-fact "$new_fact"
    ;;

  recall)
    context="${1:-}"
    n="${2:-5}"
    if [ -z "$context" ]; then
      echo "usage: $0 recall \"CONTEXT\" [N]   # L3-9: 雙路徑查詢 (search + list + smart rank)" >&2
      exit 1
    fi
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/brain_smart.py" search "$context" --limit "${n:-5}"
    ;;

  brain-stats)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/brain_smart.py" stats
    ;;

  decay)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    python3 "$SCRIPT_DIR/brain_smart.py" decay --days "${1:-30}"
    ;;

  search)
    query="${1:-}"
    n="${2:-5}"
    if [ -z "$query" ]; then
      echo "usage: $0 search \"QUERY\" [N]" >&2
      exit 1
    fi
    encoded=$(printf '%s' "$query" | jenc)
    curl -s -m 10 -X POST "$BRAIN_URL/memory/search" \
      -H "Content-Type: application/json" \
      -H "x-api-key: $API_KEY" \
      -d "{\"query\": $encoded, \"user_id\": \"$USER_ID\", \"limit\": $n}" \
      | python3 -m json.tool
    ;;

  relevant)
    context="${1:-}"
    n="${2:-5}"
    if [ -z "$context" ]; then
      echo "usage: $0 relevant \"CONTEXT\" [N]" >&2
      exit 1
    fi
    encoded=$(printf '%s' "$context" | jenc)
    curl -s -m 10 -X POST "$BRAIN_URL/brain/relevant" \
      -H "Content-Type: application/json" \
      -H "x-api-key: $API_KEY" \
      -d "{\"context\": $encoded, \"user_id\": \"$USER_ID\", \"limit\": $n}" \
      | python3 -m json.tool
    ;;

  delete)
    id="${1:-}"
    if [ -z "$id" ]; then
      echo "usage: $0 delete ID" >&2
      exit 1
    fi
    curl -s -m 10 -X DELETE "$BRAIN_URL/memory/$id" \
      -H "x-api-key: $API_KEY" | python3 -m json.tool
    ;;

  help|*)
    cat <<EOF
Mavis Brain sync (Hermes ↔ Synology NAS)

  $0 stats                    brain health + counts
  $0 pull [N]                 show N most recent memories
  $0 add "TEXT" [category]    write a new memory
  $0 extract "TEXT"           LLM-extract facts, then add all (uses MiniMax M3)
  $0 extract-stdin            same, read text from stdin
  $0 extract-session SID      same, read from hermes session log
  $0 recall "CONTEXT" [N]     smart search (search + list + client rank)
  $0 brain-stats              smart stats w/ forgetting curve
  $0 decay [N_DAYS]           show memories older than N days
  $0 summarize [CAT] [DAYS] [N]   L4-14: M3 蒸餾老記憶成 meta-fact
  $0 conflict CAT "NEW_FACT" L4-16: M3 比對新事實 vs 現有記憶
  $0 search "QUERY" [N]       keyword search
  $0 relevant "CONTEXT" [N]   semantic search (synonym-expanded)
  $0 delete ID                delete by id

Brain:   $BRAIN_URL
User:    $USER_ID
Device:  $DEVICE_ID

Categories: preference(3.0) habit(2.5) workflow(2.0) skill(2.0)
            interest(1.8) fact(1.5) context(1.5)
EOF
    ;;
esac
