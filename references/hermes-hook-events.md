# Hermes Hook Events — Quick Reference

Two separate hook systems run in Hermes. **Don't confuse them** — they have different config shapes, different event names, and different ways to test.

## System A: Gateway hooks (preferred for cross-cutting Brain sync)

| Aspect | Detail |
|---|---|
| Lives in | `~/.hermes/hooks/<name>/HOOK.yaml` + `handler.py` |
| Fired by | `gateway/run.py` — `await self.hooks.emit(event, ctx)` |
| Fires from | Anything going through the **gateway**: Telegram, Open WebUI, API server, cron, Discord, Slack, etc. |
| Does NOT fire from | `hermes chat` (CLI) — CLI sessions bypass the gateway entirely |
| Restart to load | `hermes gateway restart` |
| Test command | **None exposed** — `hermes hooks test` only tests System B (shell hooks). The "official" test for gateway hooks is "send a Telegram message, check the log file you write in handler.py" |
| Allowlist | First-use consent allowlist at `~/.hermes/shell-hooks-allowlist.json` (only for System B; gateway hooks are pre-trusted once `HOOK.yaml` is in `~/.hermes/hooks/`) |

## System B: Shell hooks (per-call transformation)

| Aspect | Detail |
|---|---|
| Lives in | `hooks:` block of `~/.hermes/config.yaml` |
| Fires from | CLI + Gateway (every shell call) |
| Restart to load | `hermes gateway restart` |
| Test command | `hermes hooks test <event>` — works! |
| Allowlist | First-use consent (config shell scripts need user OK first time) |

## Real event names (verified 2026-06-07)

Gateway emits these via `self.hooks.emit(...)` (grep for `await self.hooks.emit` in `gateway/run.py`):

| Event | When | Use case |
|---|---|---|
| `agent:start` | At the start of an agent run inside the gateway | Log "user X started session Y" |
| `agent:step` | After each tool call | Per-tool audit |
| `agent:end` | After the agent produces its final response | **Best for "extract on session end" hooks** like Brain sync |
| `pre_gateway_dispatch` | Before platform-specific dispatch | Intercept before Telegram/Slack/Discord sends |
| `post_gateway_dispatch` | After dispatch | Log/track outbound messages |
| `subagent_start` / `subagent_stop` | Around delegate_task children | Subagent audit |
| `pre_tool_call` / `post_tool_call` | Per tool (interception, audit) | Tool guardrails |

**Note**: `on_session_end` is **only** valid in the *plugin* hook system (registered via `ctx.register_hook()` in a Python plugin), NOT in `HOOK.yaml` for gateway hooks. If you put `on_session_end` in `HOOK.yaml` the gateway will load the file but never fire it. Use `agent:end` instead.

## How to verify a gateway hook actually fires (2026-06-07)

`hermes hooks test` won't help (it only tests System B). The reliable end-to-end check is:

1. Look at the gateway log for the load message:
   ```
   [hooks] Loaded hook '<your-hook-name>' for events: ['agent:end']
   ```
   If you see this, the hook is registered.

2. Trigger a session that goes **through the gateway**. The cleanest trigger is a Telegram message:
   - Send a message to the bot
   - The bot finishes responding
   - Check the log file you wrote in `handler.py`

3. Confirm via your handler's own log:
   - Write to `~/.hermes/logs/hooks/<your-hook-name>.log` from inside `handle()`
   - `tail` it after a known gateway session ends

If the log file is empty after a real session, the hook is registered but **not firing**. Re-check:
- Event name in `HOOK.yaml` is one of the verified names above
- `hermes gateway restart` was run after creating the hook
- The session went through the gateway (not `hermes chat` directly)

## Common errors

- ❌ `HOOK.yaml` with `events: on_session_end` → loads, never fires. Use `agent:end`.
- ❌ `HOOK.yaml` with `events: agent:start` → works, but you wanted `agent:end` (different meaning).
- ❌ `hermes hooks test agent:end` → "Unknown event" because the validator only knows System B events.
- ❌ Test from `hermes chat -q "..."` → hook never runs (CLI bypasses gateway). Test from Telegram.
