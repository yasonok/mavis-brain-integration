# Secret-Handling Recipe (when the user pastes a token into chat)

This file is a standalone, copy-pasteable reference for the agent (and a checklist for the user) when a `ghp_` / `xoxb-` / `sk-` / `AKIA` / JWT-shaped string appears in the conversation.

The skill's SKILL.md `Pitfall 2` covers the policy. This file covers the **exact steps** to take.

## 0. Detect

Trigger when the user message contains a string matching any of:
- `ghp_[A-Za-z0-9]{36,255}` — GitHub classic or fine-grained PAT
- `gho_[A-Za-z0-9]{36,255}` — GitHub OAuth token
- `ghu_[A-Za-z0-9]{36,255}` — GitHub user token
- `ghs_[A-Za-z0-9]{36,255}` — GitHub server token
- `ghr_[A-Za-z0-9]{36,255}` — GitHub refresh token
- `xoxb-` / `xoxp-` / `xoxa-` — Slack tokens
- `sk-` followed by 32+ chars — OpenAI / Anthropic / similar API keys
- `AKIA[0-9A-Z]{16}` — AWS access key
- `eyJ` followed by base64 (JWT)

## 1. Tell the user once, briefly

The session DB at `~/.hermes/sessions/*.db` is the canonical transcript. Direct edits risk corruption and don't actually help — the value was snapshotted into whatever the agent's loop already produced. The only real mitigation is rotate-the-credential, not edit-the-transcript.

Tell the user this in one line and move on. Don't propose sed/grep "scrub" scripts.

## 2. Worked example (this session, 2026-06-06)

User pasted a GitHub PAT (prefix `ghp_`, 40 chars) into chat, saying "你就是幫我上傳到 GITHUB".

The agent:
1. Pushed the repo using `gh repo create …` (Option A) — the PAT was **not** used.
2. Told the user the leaked PAT was now in session DB and recommended revoking it at <https://github.com/settings/tokens>.
3. Did **not** echo the PAT, did **not** commit it, did **not** try to scrub it.

Outcome: repo created, PAT never entered any tool call, user reminded to revoke. Correct.

## 3. Anti-patterns (do not do)

- ❌ Echo the secret in a follow-up message ("got it, your token is ghp_…"). Even with `***` masking, this normalizes the leak.
- ❌ Write the secret into a `~/.hermes/.env` via `hermes config set` then immediately use it in the same turn. The write itself isn't the problem, but the lesson is to **avoid** the round-trip entirely.
- ❌ Try to redact the secret from `~/.hermes/sessions/*.db` post-hoc. The DB is the canonical record; direct edits are fragile and misleading.
- ❌ Assume the user "knows what they're doing" because they've made the mistake before. The mistake repeats; the warning must repeat.

## 4. Pitfall: don't put secret-shaped strings (even partial) in committed docs

**Lesson learned 2026-06-07**: GitHub push protection scans for `ghp_` PAT pattern match, even when the string is a partial fingerprint in a *teaching document*. A reference doc that said "User pasted `ghp_lI...FTNi`" got the entire commit blocked with `remote: Push cannot contain secrets`. The full rejection was:

```
remote: —— GitHub Personal Access Token —————————————————
remote:  locations:
remote:   - commit: d8180b1...
remote:     path: references/secret-handling-recipe.md:66
remote:  (?) To push, remove secret from commit(s) or follow this URL
remote:  https://github.com/yasonok/<repo>/security/secret-scanning/unblock-secret/<id>
```

**What to do instead**:
- Use prose: "a GitHub PAT (prefix `ghp_`, 40 chars)" — never include even partial fingerprints.
- If you need an example, use a fake obviously-not-real one: `ghp_FAKE_xxxxxxxxxxxxxxxxxxxx`.
- Unblock via the URL the push output gives you — that means filing a `secret scanning allowlist` rule for the exact value (only do this if the string is genuinely fake / a fixture).
- For workflow re-do on a rejected push: `git commit --amend --no-edit && git push`. No force push needed.
