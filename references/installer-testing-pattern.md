# Testing installer / bootstrapper scripts without touching the real `$HOME`

When a skill ships an `install.sh` that writes to `~/.hermes/`, `~/.local/bin/`, and `~/.mavis/config/`, you cannot run it for real to verify — it would mutate the user's actual environment. The pattern below lets you test in a sandboxed HOME in 30 seconds.

## The trick

Override `HOME` (and `PATH` if the script calls a command like `hermes`) before invoking the script. Everything that uses `~` or `$HOME` resolves to the fake home; everything that uses absolute paths (like `which hermes`) resolves through the mock PATH.

```bash
FAKE_HOME=/tmp/fake-home-$$
mkdir -p "$FAKE_HOME/.local/bin"

# Mock any required commands as no-op stubs
cat > "$FAKE_HOME/.local/bin/hermes" <<'EOF'
#!/usr/bin/env bash
echo "MOCK HERMES: args=$*"
exit 0
EOF
chmod +x "$FAKE_HOME/.local/bin/hermes"

# Now run the installer with the fake home + mock PATH
HOME="$FAKE_HOME" \
  PATH="$FAKE_HOME/.local/bin:$PATH" \
  bash ./install.sh --device-id test-clean-install 2>&1 | head -80

# Inspect the result
find "$FAKE_HOME" -type f
cat "$FAKE_HOME/.mavis/config/brain.json"
"$FAKE_HOME/.local/bin/hermes-with-brain" --test-arg  # should call MOCK HERMES

# Clean up
rm -rf "$FAKE_HOME"
```

## What this catches (real bugs from past sessions)

- **Path quoting**: `~/.local/bin` vs `$HOME/.local/bin` — both should resolve under the override. A script that hardcodes `/Users/foo/...` will fail (correctly) and surface the bug.
- **Missing `mkdir -p` before write**: `~/.mavis/config/` will not exist in a fresh fake home, so any write without `mkdir -p` fails the smoke test.
- **Binary detection via `command -v`**: only mocks that are on PATH get found. The mock-hermes stub pattern above is the right level — just enough to satisfy `command -v hermes >/dev/null 2>&1`.
- **Smoke-test self-cleanup**: the installer's sentinel-write-then-delete roundtrip should not leave residue. Run the smoke step twice in a row to confirm idempotency.

## What this does NOT catch

- **Behavior against the real NAS / Tailscale / service**. Override HOME doesn't change network state. The smoke test in `install.sh` will hit the real Brain server if Tailscale is up; for full isolation, point `BRAIN_URL` at a mock FastAPI server (`python3 -m http.server` with a stub `/brain/stats` returns).
- **macOS-only quirks like Gatekeeper / `xattr`**. Those need a real macOS environment.
- **launchd integration** (plists in `~/Library/LaunchAgents/`). Override HOME puts the plist in `/tmp/fake-home-*/Library/LaunchAgents/`, which launchd will never read. Test plists separately with `launchctl` against a real home.

## Variations

| Want to test | Override |
|---|---|
| File writes only (no command calls) | Just `HOME=$FAKE_HOME bash script.sh` |
| Command calls too | `HOME=$FAKE_HOME PATH=$FAKE_HOME/.local/bin:$PATH bash script.sh` |
| API calls (e.g. to Brain) | Add a mock HTTP server: `python3 -m http.server 9999 &`, set `BRAIN_URL=http://127.0.0.1:9999` |
| Service integration (launchd/systemd) | Skip this pattern; use a real VM or container |

## When NOT to use this pattern

- The script's behavior depends on existing real state (e.g. a long-lived config file with permissions). Override HOME loses that state.
- The script writes outside `$HOME` (e.g. `/etc/`, `/Applications/`, `/usr/local/`). Override HOME won't redirect those. Wrap with a chroot/jail or test in a VM instead.
