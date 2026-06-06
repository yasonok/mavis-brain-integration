#!/usr/bin/env bash
# install.sh — One-shot installer for the Mavis Brain ↔ Hermes bridge
# Run on any device (Mac / Linux / WSL) that has Hermes installed.
#
# What it does:
#   1. Verifies Tailscale can reach 100.76.149.19:5188
#   2. Installs ~/.hermes/skills/mavis-brain-integration/ from the source skill
#   3. Drops a hermes-with-brain wrapper in ~/.local/bin/
#   4. Writes ~/.mavis/config/brain.json (device_id + user_id)
#   5. Runs a smoke test (stats + add/search/delete roundtrip)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
#   # OR (local copy):
#   ./install.sh
#   ./install.sh --device-id win-laptop-jason --user-id jason
#
# Re-run safely. Idempotent. Re-running overwrites the wrapper but
# preserves any memories already in Brain.

set -euo pipefail

# -------- Config (override via env or flags) ----------------------------
BRAIN_URL="${BRAIN_URL:-http://100.76.149.19:5188}"
API_KEY="${API_KEY:-0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85}"
USER_ID="${USER_ID:-jason}"
DEVICE_ID="${DEVICE_ID:-}"

# If no device_id given, try to auto-detect
if [ -z "$DEVICE_ID" ]; then
  case "$(uname -s)" in
    Darwin)
      # macOS — use hostname without .local
      HOSTNAME_SHORT=$(scutil --get ComputerName 2>/dev/null | tr ' ' '-' | tr '[:upper:]' '[:lower:]')
      [ -z "$HOSTNAME_SHORT" ] && HOSTNAME_SHORT=$(hostname -s 2>/dev/null)
      DEFAULT_DEVICE="ryans-macbook-pro"
      # If hostname matches known pattern, use it; else fall back
      DEVICE_ID="${HOSTNAME_SHORT:-$DEFAULT_DEVICE}"
      ;;
    Linux)
      DEVICE_ID="$(hostname -s)"
      ;;
    MINGW*|CYGWIN*|MSYS*)
      DEVICE_ID="win-$(hostname)"
      ;;
    *)
      DEVICE_ID="unknown-$(hostname -s)"
      ;;
  esac
fi

HERMES_SKILLS_DIR="${HERMES_HOME:-$HOME/.hermes}/skills"
INSTALL_DIR="$HERMES_SKILLS_DIR/mavis-brain-integration"
WRAPPER_DIR="$HOME/.local/bin"

# Color helpers
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
info()   { printf '\033[36m[i]\033[0m %s\n' "$*"; }

# -------- Parse flags --------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --device-id) DEVICE_ID="$2"; shift 2 ;;
    --user-id)   USER_ID="$2"; shift 2 ;;
    --brain-url) BRAIN_URL="$2"; shift 2 ;;
    --api-key)   API_KEY="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *) red "unknown flag: $1"; exit 1 ;;
  esac
done

echo "==============================================="
echo "  Mavis Brain ↔ Hermes Bridge — Installer"
echo "==============================================="
echo "Brain:    $BRAIN_URL"
echo "User:     $USER_ID"
echo "Device:   $DEVICE_ID"
echo "Hermes:   $HERMES_SKILLS_DIR"
echo "==============================================="
echo

# -------- Step 1: Hermes present? ---------------------------------------
if ! command -v hermes >/dev/null 2>&1; then
  red "❌ hermes not found on PATH"
  echo "   Install Hermes first: https://hermes-agent.nousresearch.com/docs/getting-started/installation"
  exit 1
fi
HERMES_VER=$(hermes --version 2>&1 | head -1)
green "✅ Hermes found: $HERMES_VER"

# -------- Step 2: Reachability test ------------------------------------
info "Testing Brain reachability at $BRAIN_URL ..."
if ! HEALTH=$(curl -s -m 5 "$BRAIN_URL/" 2>&1); then
  red "❌ Cannot reach $BRAIN_URL"
  echo "   Check: is Tailscale connected? Is the NAS powered on?"
  echo "   Try:   ping 100.76.149.19"
  exit 1
fi
if ! echo "$HEALTH" | grep -q "running"; then
  yellow "⚠️  Brain returned unexpected payload: $HEALTH"
  echo "   Continuing anyway — installer will still complete."
fi
green "✅ Brain reachable"

# -------- Step 3: Auth check -------------------------------------------
info "Checking API key ..."
STATS=$(curl -s -m 5 "$BRAIN_URL/brain/stats" -H "x-api-key: $API_KEY" 2>&1)
if ! echo "$STATS" | grep -q "total_memories"; then
  red "❌ API key rejected or stats endpoint failed"
  echo "   Response: $STATS"
  echo "   Get a fresh key from: $BRAIN_URL/admin or NAS ~/mavis-brain/.apikey"
  exit 1
fi
TOTAL=$(echo "$STATS" | python3 -c "import json,sys;print(json.load(sys.stdin)['total_memories'])" 2>/dev/null || echo "?")
green "✅ Auth OK. Brain has $TOTAL memories."

# -------- Step 4: Install skill ----------------------------------------
info "Installing skill to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR/scripts" "$INSTALL_DIR/references"

# Detect if we're running from a local checkout (skill files in PWD)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/SKILL.md" ]; then
  # Local source — copy
  cp "$SCRIPT_DIR/SKILL.md" "$INSTALL_DIR/SKILL.md"
  cp "$SCRIPT_DIR/scripts/sync.sh" "$INSTALL_DIR/scripts/sync.sh"
  cp "$SCRIPT_DIR/scripts/verify_brain.py" "$INSTALL_DIR/scripts/verify_brain.py" 2>/dev/null || true
  cp "$SCRIPT_DIR/references/"*.md "$INSTALL_DIR/references/" 2>/dev/null || true
  green "✅ Installed from local source"
elif [ -d "$HERMES_SKILLS_DIR/mavis-brain-integration" ] && [ -f "$INSTALL_DIR/SKILL.md" ]; then
  yellow "⚠️  Skill already exists at $INSTALL_DIR — keeping existing version"
else
  red "❌ No SKILL.md found at $SCRIPT_DIR"
  echo "   Run from the directory containing SKILL.md, or provide a local path."
  exit 1
fi

chmod +x "$INSTALL_DIR/scripts/sync.sh" 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/verify_brain.py" 2>/dev/null || true

# -------- Step 5: Drop the wrapper -------------------------------------
info "Installing hermes-with-brain wrapper ..."
mkdir -p "$WRAPPER_DIR"

cat > "$WRAPPER_DIR/hermes-with-brain" <<WRAPPER_EOF
#!/usr/bin/env bash
# hermes-with-brain — calls real hermes, with optional Brain context injection
# Generated by mavis-brain-integration installer.
#
# Behavior:
#   - Before invoking hermes, run a brain/relevant query and inject top results
#     as a [from Mavis Brain] block into the first user message of the session.
#   - On exit, run a smoke write to Brain to confirm the device is reachable.
#
# Environment (overridable):
#   BRAIN_URL  default: $BRAIN_URL
#   API_KEY    default: <elided>
#   USER_ID    default: $USER_ID
#   DEVICE_ID  default: $DEVICE_ID

set -euo pipefail

BRAIN_URL="\${BRAIN_URL:-$BRAIN_URL}"
API_KEY="\${API_KEY:-$API_KEY}"
USER_ID="\${USER_ID:-$USER_ID}"
DEVICE_ID="\${DEVICE_ID:-$DEVICE_ID}"

# Quick reachability check
if ! curl -s -m 3 -o /dev/null "\$BRAIN_URL/"; then
  echo "[brain] unreachable (\$BRAIN_URL) — falling back to local hermes with no Brain context" >&2
  exec hermes "\$@"
fi

# Pull top-N relevant memories and stash in env var
BRAIN_CTX=\$(curl -s -m 3 -X POST "\$BRAIN_URL/brain/relevant" \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: \$API_KEY" \\
  -d '{"context":"user preferences habits skills workflows","limit":8,"user_id":"'\$USER_ID'"}' \\
  2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    rs = d.get('results', d.get('memories', []))
    for m in rs[:8]:
        cat = m.get('category', '?')
        c = m.get('content', '')[:140]
        print(f'  - [{cat}] {c}')
except Exception as e:
    print(f'  (failed to parse: {e})', file=sys.stderr)
" 2>/dev/null || echo "  (no memories retrieved)")

# Inject into Hermes system context via HERMES_EXTRA_SYSTEM env var
export HERMES_EXTRA_SYSTEM="\${HERMES_EXTRA_SYSTEM:-}
[from Mavis Brain — cross-device context, pulled at session start]
\$BRAIN_CTX
[/from Mavis Brain]"

exec hermes "\$@"
WRAPPER_EOF

chmod +x "$WRAPPER_DIR/hermes-with-brain"
green "✅ Wrapper installed at $WRAPPER_DIR/hermes-with-brain"

# Add ~/.local/bin to PATH advice if not present
case ":$PATH:" in
  *":$WRAPPER_DIR:"*) ;;
  *) yellow "⚠️  $WRAPPER_DIR is not on your PATH"
     echo "   Add to ~/.zshrc or ~/.bashrc:"
     echo "     export PATH=\"\$HOME/.local/bin:\$PATH\""
     ;;
esac

# -------- Step 6: Write brain.json -------------------------------------
info "Writing ~/.mavis/config/brain.json ..."
mkdir -p "$HOME/.mavis/config"
cat > "$HOME/.mavis/config/brain.json" <<JSON
{
  "enabled": true,
  "server_url": "$BRAIN_URL",
  "api_key": "$API_KEY",
  "device_id": "$DEVICE_ID",
  "user_id": "$USER_ID"
}
JSON
green "✅ brain.json written (device_id=$DEVICE_ID)"

# -------- Step 7: Smoke test ------------------------------------------
info "Running smoke test (stats + add/search/delete roundtrip) ..."
SENTINEL="mavis-brain-installer-smoke-$(date +%s)"

# Add
ADD_RESULT=$(curl -s -m 5 -X POST "$BRAIN_URL/memory/add" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d "{\"content\":\"$SENTINEL\",\"category\":\"test\",\"user_id\":\"$USER_ID\",\"device_id\":\"$DEVICE_ID\",\"source\":\"installer\"}")
if ! echo "$ADD_RESULT" | grep -q "true\|success"; then
  yellow "⚠️  add returned: $ADD_RESULT"
fi

# Search
sleep 1
FOUND=$(curl -s -m 5 -X POST "$BRAIN_URL/memory/search" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $API_KEY" \
  -d "{\"query\":\"$SENTINEL\",\"user_id\":\"$USER_ID\",\"limit\":5}")

if echo "$FOUND" | grep -q "$SENTINEL"; then
  green "✅ search found sentinel"
else
  yellow "⚠️  search did not find sentinel — write may have lagged"
  echo "   Response: $FOUND"
fi

# Clean up
curl -s -X DELETE "$BRAIN_URL/memory?category=test" \
  -H "x-api-key: $API_KEY" > /dev/null

# -------- Final stats ---------------------------------------------------
echo
green "==============================================="
green "  Installation complete!"
green "==============================================="
echo
echo "  Brain has $TOTAL memories (before sentinel test)."
echo "  Device ID: $DEVICE_ID"
echo "  User ID:   $USER_ID"
echo
echo "  Usage:"
echo "    hermes-with-brain                    # interactive REPL with Brain context"
echo "    ~/.hermes/skills/mavis-brain-integration/scripts/sync.sh pull 10"
echo "    ~/.hermes/skills/mavis-brain-integration/scripts/sync.sh add \"TEXT\" fact"
echo
echo "  From another device, verify you can see this device's writes:"
echo "    ~/.hermes/skills/mavis-brain-integration/scripts/sync.sh search \"$DEVICE_ID\""
echo
