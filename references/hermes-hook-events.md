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

## System B: Shell hooks (config.yaml)

| Aspect | Detail |
|---|---|
| Lives in | `~/.hermes/config.yaml` under `hooks:` key |
| Fires from | Both CLI and gateway |
| Restart to load | New session (`/reset`) |
| Test command | `hermes hooks test <event>` — e.g. `hermes hooks test on_session_end` |
| Allowlist | Same `~/.hermes/shell-hooks-allowlist.json` (consented on first use) |

## Event name catalogue (from `hermes hooks test` output)

These are the events **System B** accepts (System A accepts a different set; see below):

```
api_request_error
on_session_end
on_session_finalize
on_session_reset
on_session_start
post_api_request
post_approval_response
post_llm_call
post_tool_call
pre_api_request
pre_approval_request
pre_gateway_dispatch
pre_llm_call
pre_tool_call
subagent_start
subagent_stop
transform_llm_output
transform_terminal_output
transform_tool_result
```

## System A event names (from `gateway/run.py`)

The gateway's actual emit sites use **non-prefixed** names. To find what's really emitted, grep the gateway source:

```bash
grep -nE "self\.hooks\.emit\(" ~/.hermes/hermes-agent/gateway/run.py
```

Confirmed emits as of 2026-06-07:
- `agent:end` — fired after the gateway finishes processing a response (this is the one you want for "save after every conversation")
- `agent:start` — fired at the beginning (for "load context before answering")
- Other events may exist; check the source rather than relying on the System B list

## Common mistake: pasting System B event names into System A HOOK.yaml

```yaml
# WRONG — System A's `on_session_end` will silently never fire
events:
  - on_session_end

# CORRECT — System A's emit site is `agent:end`
events:
  - agent:end
```

The gateway loads the HOOK.yaml but the event never gets emitted under that name, so the hook is effectively dead. There is no warning. The only symptom is "nothing happens when sessions end."

## The 60-second diagnostic recipe for "why isn't my hook firing"

```bash
# 1. Is the hook loaded?
hermes gateway restart
tail -20 ~/.hermes/logs/gateway.log | grep -i hook
# expect: [hooks] Loaded hook '<name>' for events: ['agent:end']

# 2. Is the right event name in the HOOK.yaml?
cat ~/.hermes/hooks/<name>/HOOK.yaml
# confirm events: contains a name from gateway/run.py's emit sites

# 3. Did the gateway see traffic?
tail -50 ~/.hermes/logs/gateway.log | grep -iE "inbound message|response ready"
# confirm sessions are actually happening

# 4. Did the hook write to its log file?
ls -la ~/.hermes/logs/hooks/ 2>/dev/null
cat ~/.hermes/logs/hooks/<your-hook>.log 2>/dev/null
# if empty, the hook handler ran but produced no output (or never ran)
```

## When to use which system

| Use case | System |
|---|---|
| Save conversation to Brain after every Telegram message | A (gateway, `agent:end`) |
| Auto-format dangerous shell commands before they run | B (shell, `pre_tool_call`) |
| Add a fixed prefix to every LLM response | B (shell, `transform_llm_output`) |
| Run on `hermes chat -q` one-shots too | B (shell) — System A skips CLI |
| Need a Python handler with full async + log file | A (gateway) |
| Just need a bash one-liner to fire on an event | B (shell, `~/.hermes/config.yaml`) |

If your hook needs to fire on `hermes chat` CLI sessions, **only System B covers that path.**
