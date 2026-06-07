# MiniMax M3 LLM — quirks for structured-output extraction

Lessons from building `extract_facts.py` (2026-06-07). When you ask M3 to produce JSON, expect this.

## Quirk 1: M3 wraps JSON in markdown ```json fences

Even when you say "嚴格 JSON array, 不要其他文字", the model will return:

```
```json
[{"fact": "...", ...}]
```
```

It treats "strict" as a recommendation, not a rule. **Always strip the fence** before parsing. A two-stage regex is the most reliable:

```python
# Stage 1: try fenced ```json``` or ```<anything>```
m = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
# Stage 2: fall back to bare array
if not m:
    m = re.search(r'\[[\s\S]*\]', content)
# Note: stage 2 must be GREEDY (`[\s\S]*`, not `[\s\S]*?`)
# because M3 sometimes adds trailing text after the closing `]`.
if not m:
    return []  # extraction failed
json_text = m.group(1) if m.lastindex else m.group(0)
```

The non-greedy `*?` catches a partial array; greedy catches the whole.

## Quirk 2: M3 sometimes adds a thinking-style block before the JSON

`content[].type` in the API response can be `"thinking"` (with a `signature` field) **in addition to** `"text"`. Iterate through all content blocks and concatenate the `text` ones; ignore the `thinking` blocks (or include them too, your call — they're usually empty for short outputs).

```python
content = ""
for c in result.get("content", []):
    if c.get("type") == "text":
        content += c.get("text", "")
```

## Quirk 3: M3 cannot generate images, even when asked

Direct prompt test (2026-06-07): ask M3 to "Generate an image and output as base64" → M3 replies with a thinking block saying "I am a text-based AI assistant and I don't have image generation capabilities." M3 is text-only at the API level.

**If you need image generation, use the Mavis/MiniMax MCP `image_synthesize` endpoint** instead (it lives at `agent.minimax.io/mavis/api/v1/mcp/image_synthesize`, **not** at `api.minimax.io/v1/images/generations` — the public chat completions API has no image endpoint, only the MCP backend does).

## Quirk 4: M3 reliability for short Chinese text

When the input is short Chinese (under 100 chars), M3 sometimes returns "No memorable facts found" even when there clearly are facts. Two mitigations:

- Provide 2-3 example facts in the prompt (`[例如: "使用者偏好...", "使用者習慣..."]`) so M3 has a calibration target.
- Lower the bar in the prompt from "值得長期記住" to "**對 Jason 未來決策可能有用的**".

The defaults on `extract_facts.py` work for ~80% of inputs. For the other 20%, prepend an example block.

## Quirk 5: JSON schema validation is your job, not M3's

M3 will sometimes:
- Omit fields you declared as required
- Use a `category` value you didn't list (e.g. "general" instead of "preference")
- Use `importance` as a string when you said integer

Always post-validate and coerce:

```python
valid = []
for f in facts:
    if not isinstance(f, dict):
        continue
    fact = f.get("fact", "").strip()
    if not fact or len(fact) > 200:
        continue  # skip empty or absurdly long
    valid.append({
        "fact": fact,
        "category": f.get("category", "fact"),  # default if missing
        "importance": max(0, min(10, int(f.get("importance", 5)))),  # coerce + clamp
        "tags": (f.get("tags", []) or [])[:5],  # default + cap
    })
return valid
```

Reject silently rather than raise — the extraction pipeline should degrade to "0 facts" on a bad LLM response, not crash.

## Quirk 6: `client.chat.completions` vs Anthropic-format messages

Hermes config uses `api_mode: chat_completions` with the OpenAI-style `messages[].role` and `messages[].content` shape. If you call M3 directly via `urllib` and you accidentally use Anthropic's `/v1/messages` endpoint format with the Bearer token, it **works** (MiniMax's `/anthropic/v1/messages` is compatible) — but the `x-api-key` header is ignored, only `Authorization: Bearer` matters. So don't accidentally double-set auth.

**For maximum compatibility, use**:
- URL: `https://api.minimax.io/anthropic/v1/messages`
- Header: `Authorization: Bearer <MINIMAX_API_KEY>`
- Body: Anthropic-format `{"model": "...", "max_tokens": N, "messages": [{"role": "user", "content": "..."}]}`

This is the recipe `extract_facts.py` uses and it works.
