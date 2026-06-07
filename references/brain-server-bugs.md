# Mavis Brain Server Bugs (workarounds required)

The Brain server on Synology NAS is locked to a single
`mavis_brain_server.py` (~515 lines, FastAPI + SQLite). It
**cannot be redeployed** without disrupting the production 50+
memories. These bugs require client-side workarounds. **Updated 2026-06-07.**

## Bug 1: FastAPI route conflict on /memory/{id}

```python
@app.get("/memory/{memory_id}")          # line 280
@app.get("/memory/entity/{a}/{b}")       # line 298 -- SHADOWED
@app.get("/sync/pull")                    # line 463 -- SHADOWED
@app.get("/sync/push")                    # line 481 -- SHADOWED (in POST but same pattern)
```

FastAPI matches the **first** registered route. So:

| Request | What you expect | What happens |
|---|---|---|
| `GET /memory/entity/user/jason` | list Jason's memories | **404** (matches `/memory/{id}` with id="entity/user/jason" and then 404 because no such id) |
| `GET /sync/pull` | bulk pull | **404** |
| `GET /sync/push` | (POST only, no GET) | n/a |

**Client workaround**: skip `/memory/entity/...` and `/sync/*`
entirely. Use the search endpoint with an empty query as a "list
all" fallback:

```python
# Replace /memory/entity/user/jason?limit=200
results = brain_request("/memory/search", "POST", {
    "query": "", "user_id": "jason", "limit": 200
}).get("results", [])
```

The server returns `ORDER BY confidence DESC, created_at DESC`
so empty-query search is approximately "most recent first".

## Bug 2: `importance` column exists but INSERT does not populate it

The server's CREATE TABLE includes `importance REAL DEFAULT 0.5`
(line 58 of server.py), so the column is there. But the
`/memory/add` INSERT statements (line 217-235) do **not** include
`importance` in the column list or values tuple. Result: every
new memory has `importance=0.5` regardless of what the client
sent.

**Client workaround**: pass importance via the `metadata` object
(also a no-op server-side, but preserved in the JSON column).
The `brain_smart.py` module reads `metadata.importance` for
scoring; if the server is ever upgraded to honor the field, no
client change is needed.

```python
add_memory(
    content="...",
    importance=8,  # put in metadata.importance
    metadata={"importance": 8, "is_context": False},
)
```

## Bug 3: `/memory/search` is too strict

The search query is split on whitespace and each term is
required as a substring in `content` OR `tags` (LIKE %term%).
Result: searching for "Cursor IDE" returns 0 hits if the
memory only contains "Cursor" without "IDE".

**Client workaround**: do a dual-path search (server search +
client keyword filter on a recent batch). See
`brain_smart.py::smart_search()`.

## Bug 4: `created_at` has no timezone

Server uses `datetime.now().isoformat()` (naive) instead of
`datetime.now(timezone.utc).isoformat()`. Python's
`datetime.fromisoformat()` parses it as a **naive** datetime.
If you compute `age = datetime.now() - created_at`, you get
the local-time delta, which is wrong if your client timezone
differs from the server timezone.

**Client workaround**: parse as naive and assume local time on
both ends. The errors are small (< 1 day) and self-correcting.

```python
def age_in_days(created_at: str) -> float:
    ts = datetime.fromisoformat(created_at)  # naive
    return (datetime.now() - ts).total_seconds() / 86400
```

## Bug 5: `/brain/evolve` accepts POST but the client function says GET

`mavis_brain_client.py` (the reference client) sends
`/brain/evolve` as a POST but the reference documentation
listed it as GET. The server endpoint is `POST /brain/evolve`
and it works. The client comment is just wrong.

This is a docs bug, not a server bug. Not a blocker.

## Bug 6: Server has no /memory/list or /sync/pull endpoint

The server description advertises these but the route conflict
(Bug 1) makes them 404. **No workaround in the server.** Use
`search` with empty query for "list all" (Bug 1 workaround).

## When the server gets redeployed

If the user does eventually redeploy the server (e.g., to fix
the route conflict by reordering), the `metadata.importance`
field will start being honored. No client change needed.
