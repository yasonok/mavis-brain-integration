# Hermes Gateway Hooks vs Shell Hooks

Hermes has **two independent hook systems** that fire on different events
and run in different contexts. Confusing them is a top-3 time-sink in
Brain integration work.

## System A: Gateway Hooks (PREFERRED for cross-cutting Brain sync)

| Aspect | Detail |
|---|---|
| Lives in | `~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py` |
| Fired by | `gateway/run.py` -> `await self.hooks.emit(event, ctx)` |
| Fires from | Anything going through the **gateway**: Telegram, Open WebUI, API server, cron, Discord, Slack, etc. |
| Does NOT fire from | `hermes chat` (CLI) -- CLI sessions bypass the gateway entirely |
| Restart to load | `hermes gateway restart` |
| Test command | **None exposed** -- `hermes hooks test` only tests System B. Test by sending a Telegram message and reading your handler's log file |
| Allowlist | First-use consent allowlist at `~/.hermes/shell-hooks-allowlist.json` (only for System B; gateway hooks are pre-trusted once `HOOK.yaml` is in `~/.hermes/hooks/`) |

### HOOK.yaml format

```yaml
name: mavis-brain-auto-extract
description: "Session-end hook that auto-extracts memorable facts from each Hermes session and syncs them to Mavis Brain."
events:
  - agent:end    # NOT on_session_end -- see event name table below
```

### handler.py signature

```python
import json
from datetime import datetime
from pathlib import Path

LOG_FILE = Path.home() / ".hermes" / "logs" / "hooks" / "my-hook.log"

async def handle(event_type: str, context: dict) -> None:
    """Called for each subscribed event. Must be named 'handle'."""
    if event_type != "agent:end":
        return
    session_id = context.get("session_id") or context.get("sessionId")
    if not session_id:
        return
    # ... do work, write to LOG_FILE
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(), "sid": session_id}) + "\n")
```

### Event names (gateway hooks)

The correct event for "session finished" is **`agent:end`**, not
`on_session_end`. The latter is for **shell hooks** (System B).

Other gateway events you might want:
- `agent:start` — fires when a new session starts
- `agent:step` — fires after every LLM tool call
- `command:*` — wildcard for slash commands

## System B: Shell Hooks (in config.yaml)

| Aspect | Detail |
|---|---|
| Lives in | `hooks:` block of `~/.hermes/config.yaml` |
| Fires from | Both CLI and gateway (Hermes shell command interception) |
| Use case | Format-checking, blocking, context injection, side effects on specific commands |
| Test | `hermes hooks test <event>` |

### Event names (shell hooks)

Valid events include: `api_request_error`, `on_session_end`,
`on_session_finalize`, `on_session_reset`, `on_session_start`,
`post_api_request`, `post_approval_response`, `post_llm_call`,
`post_tool_call`, `pre_api_request`, `pre_approval_request`,
`pre_gateway_dispatch`, `pre_llm_call`, `pre_tool_call`,
`subagent_start`, `subagent_stop`, `transform_llm_output`,
`transform_terminal_output`, `transform_tool_result`.

Note: `agent:end` is **NOT** in this list. They are different
namespaces; cross-pollinating the names silently produces no-op
hooks (you'll see "Loaded hook X for events: [agent:end]" but the
hook never fires from `hermes chat`).

## Debugging

1. Check `~/.hermes/logs/gateway.log` for the `Loaded hook X for events` line after a restart
2. Send a real message via Telegram (or whatever platform you target)
3. Tail your handler's log file
4. If nothing appears, your event name is wrong (System A vs System B confusion)

The dead giveaway: the gateway log says "Loaded" but the handler
never runs. This is the symptom of either a wrong event name OR a
CLI-only session (System A doesn't fire from `hermes chat`).
