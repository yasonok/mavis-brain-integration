# M3 Prompt Design & JSON Parsing Patterns

## M3 Prompt Anatomy (works for MiniMax M3 / Anthropic API)

M3 is a text-generation model. Treat prompts as **structured specification**, not conversation.

### Anatomy of a working prompt (5 layers)

```
1. Role     — "你是 Jason 的「個人記憶蒸餾器」"  (set persona + scope)
2. Schema   — explicit category list with definitions + judgement rubric
3. Rules    — N hard constraints (1-5 facts, 10-30 chars, importance 0-10)
4. Examples (optional) — if M3 keeps miscategorizing
5. Output   — exact JSON template + closing "JSON:" tag
```

**Why the closing `JSON:` tag works**: M3 is autoregressive; the tag
gives it a generation target. Without it, M3 often says "OK, here's my
analysis:" and writes prose instead of JSON.

### Layer 2 must be a TABLE not a one-liner

Bad:  "categories: preference, workflow, fact, skill, ..."
Good: each category gets **definition + 1 example + 1 judgement cue**

```
- **preference**: Jason 喜歡/討厭/習慣的東西, 例 "..."
  cue: "我喜歡 X" / "I prefer X"
- **workflow**: Jason 怎麼做事的 SOP, 例 "..."
  cue: "我平常都這樣做" / "I always do X this way"
```

This gets M3 categorisation accuracy from ~60% to ~85%+ in practice.

## JSON Parsing (fault-tolerant, 3 levels)

M3 sometimes wraps JSON in ```json``` markdown blocks, sometimes
returns raw JSON, sometimes returns prose. Always try in this order:

```python
# Level 1: markdown code block
m = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', content, re.DOTALL)
# Level 2: bare brace / bracket delimited
if not m:
    m = re.search(r'\{[^{}]*"<key>"\s*:\s*[^{}]*\}|^\s*\[', content, re.DOTALL)
# Level 3: first non-empty line as fallback
if not m:
    first = content.strip().split("\n")[0].strip()
    # filter out "I don't have enough context" / "Please provide X" replies
    if first and 5 < len(first) < 200 and "請提供" not in first and "無法" not in first:
        return first
```

For arrays: re.search pattern uses `\[.*?\]` but be aware of
**non-greedy matching pitfalls** — for nested structures, the
outer pattern may stop at the first inner `]`. Prefer
greedy `\[.*\]` with re.DOTALL when the structure is known to be a
single top-level array.

## M3 Returns Empty String

If M3 returns `content = ""`, the request likely:
- exceeded the context window (truncate to <3000 chars at the prompt level)
- hit a rate limit (retry once after 5s)
- the model refused due to safety trigger (rephrase the prompt)

Debug by dumping `repr(content[:500])` to stderr.

## Importance Scoring Calibration

When asking M3 to rate importance 0-10:
- 0-2:  ephemeral, debug, single-session context
- 3-4:  general facts that will matter in the next week
- 5-6:  user preferences, workflows, recurring tools
- 7-8:  identity, security-related, money
- 9-10: passwords, security incidents, account compromises

M3 tends to inflate. Subtract 1-2 from raw M3 output if you want a
calibrated 0-10 scale. Example: M3 rates "user prefers short
responses" as 7; humans would say 5.
