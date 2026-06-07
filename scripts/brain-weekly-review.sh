#!/usr/bin/env bash
# brain-weekly-review.sh - Weekly Brain health summary, delivered to Telegram.
# Hermes cron migration: client-side brain health check
# Schedule: Sundays 23:00 Asia/Taipei
# Cron registration:
#   hermes cron create "0 23 * * 0" --name brain-weekly-review \
#     --deliver "telegram:7825900351" --script brain-weekly-review.sh --no-agent
#
# Note: --script takes a BASENAME relative to ~/.hermes/scripts/, NOT an absolute path.
# Place this file at ~/.hermes/scripts/brain-weekly-review.sh.
#
# Disable set -e/pipefail: hermes send in a pipe can fail without aborting the whole review.

SYNC="$HOME/.hermes/skills/mavis-brain-integration/scripts/sync.sh"
TELEGRAM_CHAT="7825900351"

if [ ! -x "$SYNC" ]; then
  echo "ERROR: sync.sh not found at $SYNC" >&2
  exit 1
fi

echo "=== Brain Weekly Review $(date '+%Y-%m-%d %H:%M %Z') ==="

# 1. Smart stats (client-side ranking by category avg score)
STATS=$("$SYNC" brain-stats 2>&1 || echo "(stats failed)")

# 2. Decay warning: memories older than 90 days, sorted by score ascending
DECAY=$("$SYNC" decay 90 2>&1 | head -40 || echo "(decay check failed)")

# 3. Compose message (build via temp file to avoid heredoc quoting issues)
MSG_FILE=$(mktemp)
printf '%s\n' "$STATS" > "$MSG_FILE"
printf '\n--- Decay (90+ days) ---\n' >> "$MSG_FILE"
printf '%s\n' "$DECAY" >> "$MSG_FILE"

# 4. Send to Telegram via hermes send
hermes send -t "telegram:$TELEGRAM_CHAT" -f "$MSG_FILE" 2>/dev/null || echo "[brain-weekly-review] telegram send skipped"
rm -f "$MSG_FILE"

echo "=== Done ==="
