# Secret-Handling Recipe (when the user pastes a token into chat)

This file is a standalone, copy-pasteable reference for the agent (and a checklist for the user) when a `ghp_` / `xoxb-` / `sk-` / `AKIA` / JWT-shaped string appears in the conversation.

The skill's SKILL.md `Pitfall 2` covers the policy. This file covers the **exact steps** to take.

## 0. Detect

Trigger when the user message contains a string matching any of:
- `ghp_[A-Za-z0-9]{36,255}` — GitHub classic or fine-grained PAT
- `gho_…`, `ghu_…`, `ghs_…`, `ghr_…` — GitHub OAuth / user-to-server / installation / refresh tokens
- `xoxb-…`, `xoxp-…`, `xoxa-…`, `xoxs-…` — Slack tokens
- `sk-…` (≥20 chars) — OpenAI / Anthropic / OpenRouter
- `AKIA[A-Z0-9]{16}` — AWS access key
- `eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}` — JWT
- Any string the user explicitly identifies as "token" / "key" / "secret" / "password"

## 1. Stop and warn (one sentence)

> "That value is now in the session DB and possibly the logs. Hermes' tool-output redaction only masks on display, not at rest, so consider it compromised the moment it landed here."

Don't bury this in a wall of text. One line.

## 2. Offer three options, in this order

**Option A — Use a tool that already has the secret out-of-band.**

Examples that work without a token in the command line on this machine:
- `gh` CLI is authenticated via the macOS keyring. `gh repo create …`, `gh api …`, `gh auth status` — none need a PAT in argv.
- `hermes config set TELEGRAM_BOT_TOKEN "…"` writes to `~/.hermes/.env` without exposing the value to the agent's tool surface (the read is redacted; the value is persisted).
- `aws s3 cp …` with `aws configure` already done (uses `~/.aws/credentials`).

**Option B — Stash to a tmpfile.**

```bash
# User runs in their terminal:
echo 'PASTE_NEW_TOKEN_HERE' > /tmp/<short-purpose>_token
chmod 600 /tmp/<short-purpose>_token
```

Tell the user to say "token at /tmp/<short-purpose>_token". The agent then runs `cat /tmp/<short-purpose>_token` to get the value. The session transcript contains only the path, never the secret.

Always remind: `rm /tmp/<short-purpose>_token` after the operation.

**Option C — Paste into the target tool's UI directly.**

For example, the GitHub PAT creation page, the Telegram @BotFather chat, the AWS console. The agent's chat is never the destination.

## 3. After the operation succeeds, remind the user to revoke the old value

Provide the exact path or command:
- GitHub PAT: <https://github.com/settings/tokens>
- Telegram bot: `@BotFather` → `/revoke`
- Slack: <https://api.slack.com/apps> → "Revoke" on the app
- AWS: `aws iam delete-access-key --access-key-id AKIA… --user-name <user>`
- OpenAI: <https://platform.openai.com/api-keys>

## 4. Don't try to "clean" the leaked value from session DB or logs

The session DB at `~/.hermes/sessions/*.db` is the canonical transcript. Direct edits risk corruption and don't actually help — the value was snapshotted into whatever the agent's loop already produced. The only real mitigation is rotate-the-credential, not edit-the-transcript.

Tell the user this in one line and move on. Don't propose sed/grep "scrub" scripts.

## Worked example (this session, 2026-06-06)

User pasted a GitHub PAT (prefix `ghp_`, 40 chars) into chat, saying "你就是幫我上傳到 GITHUB".

The agent:
1. Pushed the repo using `gh repo create …` (Option A) — the PAT was **not** used.
2. Told the user the leaked PAT was now in session DB and recommended revoking it at <https://github.com/settings/tokens>.
3. Did **not** echo the PAT, did **not** commit it, did **not** try to scrub it.

Outcome: repo created, PAT never entered any tool call, user reminded to revoke. Correct.

## Anti-patterns (do not do)

- ❌ Echo the secret in a follow-up message ("got it, your token is ghp_…"). Even with `***` masking, this normalizes the leak.
- ❌ Write the secret into a `~/.hermes/.env` via `hermes config set` then immediately use it in the same turn. The write itself isn't the problem, but the lesson is to **avoid** the round-trip entirely.
- ❌ Try to redact the secret from `~/.hermes/sessions/*.db` post-hoc. The DB is the canonical record; direct edits are fragile and misleading.
- ❌ Assume the user "knows what they're doing" because they've made the mistake before. The mistake repeats; the warning must repeat.
- ❌ Promise "I've cleaned it up" after attempting any kind of post-hoc scrub. The only safe claim is "rotate the credential."
