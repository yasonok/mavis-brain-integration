# NAS + Tailscale Access Pattern

## Topology

```
       Tailscale 100.x overlay network
       ┌──────────────────────────────────────────┐
       │                                          │
  ┌────┴─────┐  ┌─────────┐  ┌────────┐  ┌────┴────┐
  │ MacBook  │  │ iPhone  │  │ iPad   │  │ Win PC  │
  │ 100.x.A  │  │ 100.x.B │  │ 100.x.C│  │ 100.x.D │
  └────┬─────┘  └─────────┘  └────────┘  └─────────┘
       │                all talk to:                │
       └────────> 100.76.149.19:5188  <───────────┘
                   (Synology NAS, Tailscale IP)
                   Mavis Brain FastAPI
```

## Connection

Brain server URL: **http://100.76.149.19:5188** (Tailscale, not LAN)
API key (header): **x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85**
(deployment key, not a per-user secret -- safe to commit to repos
since Brain sits on a private tailnet)

## Reaching Brain from the Agent

Two routes:

### Route 1: REST API (preferred for code)

```bash
curl -s -X POST http://100.76.149.19:5188/memory/search \
  -H "Content-Type: application/json" \
  -H "x-api-key: 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85" \
  -d '{"query":"ETF","limit":5}'
```

### Route 2: Python client (preferred for scripts)

Use the inlined `search_memory()`, `add_memory()`, `list_recent_memories()`
functions from `scripts/extract_facts.py` or `scripts/brain_smart.py`.
They handle auth + JSON serialization.

## Common Failure Modes

| Symptom | Cause | Fix |
|---|---|---|
| Connection refused | NAS asleep or Tailscale down | wake NAS, check `tailscale status` |
| 401 Unauthorized | API key rotated | read new key from NAS `~/mavis-brain/.apikey` |
| Timeout | NAS overload or network slow | retry with shorter timeout; check `top` on NAS via SSH |
| 500 from /memory/add | SQLite locked (concurrent writes) | retry once after 1s |

## SSH Into NAS (admin tasks only)

The Brain server source lives at
`~/.minimax/scratchpads/*/workspace/mavis_brain_server.py` (read
from local copy). The actual NAS source is at
`/volume2/homes/yasonok02061/mavis-brain/` (in
`mavis_brain_server.py`).

SSH access requires the user's `id_ed25519` public key to be in
`~/.ssh/authorized_keys` on the NAS. Hermes agent does not
have direct SSH access; if you need to inspect the live server,
ask the user to run the command.

## Tailscale IP May Change

Tailscale IPs are stable per device but can change if the user
rebuilds the NAS or Tailscale reconfigures. The DNS name
`<nas>.ts.net` (Tailscale MagicDNS) is more stable. If Brain
becomes unreachable, ping `100.76.149.19` first; if that fails,
ask the user to check Tailscale on the NAS.
