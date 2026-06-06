#!/usr/bin/env python3
"""
verify_brain.py — End-to-end smoke test for the Mavis Brain integration.

Run after wiring Hermes to Brain to confirm auth, add, search, and delete all
work. Exit code 0 = all green. Non-zero = the integration is broken somewhere.

Usage:
    python3 verify_brain.py [--server http://100.76.149.19:5188]
                            [--key 0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85]
                            [--skip-cleanup]   # leave the test memory behind

The defaults match the user's deployment on Synology NAS DS220j.
"""

import argparse
import json
import sys
import time

import requests

DEFAULT_SERVER = "http://100.76.149.19:5188"
DEFAULT_KEY = "0e627d44-61c4-4a7f-97e8-e9dd1a3c7a85"
TIMEOUT = 5  # seconds; brain calls should be fast or fail loudly


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--key", default=DEFAULT_KEY)
    parser.add_argument("--skip-cleanup", action="store_true")
    args = parser.parse_args()

    h = {"x-api-key": args.key, "Content-Type": "application/json"}
    base = args.server.rstrip("/")
    failures: list[str] = []

    # 1. Health
    print("[1/5] health check …", end=" ")
    try:
        r = requests.get(f"{base}/", timeout=TIMEOUT)
        if r.status_code == 200 and "running" in r.text:
            print("OK")
        else:
            print(f"FAIL ({r.status_code})")
            failures.append(f"health: HTTP {r.status_code}")
    except requests.RequestException as e:
        print(f"FAIL ({e})")
        failures.append(f"health: {e}")
        return 1  # no point continuing

    # 2. Stats
    print("[2/5] stats …", end=" ")
    before = 0
    try:
        r = requests.get(f"{base}/brain/stats", headers=h, timeout=TIMEOUT)
        r.raise_for_status()
        before = r.json().get("total_memories", 0)
        print(f"OK ({before} memories)")
    except (requests.RequestException, KeyError) as e:
        print(f"FAIL ({e})")
        failures.append(f"stats: {e}")

    # 3. Add sentinel
    print("[3/5] add sentinel …", end=" ")
    sentinel = f"verify-brain-{int(time.time())}"
    try:
        r = requests.post(
            f"{base}/memory/add",
            headers=h,
            json={"content": sentinel, "category": "test", "source": "verify-brain.py"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        print("OK")
    except requests.RequestException as e:
        print(f"FAIL ({e})")
        failures.append(f"add: {e}")

    # 4. Search for sentinel
    print("[4/5] search for sentinel …", end=" ")
    try:
        time.sleep(0.5)  # let the index settle
        r = requests.post(
            f"{base}/memory/search",
            headers=h,
            json={"query": sentinel, "limit": 5},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        found = any(sentinel in str(m) for m in r.json().get("result", []))
        if found:
            print("OK")
        else:
            print(f"FAIL (sentinel not in results: {r.text[:200]})")
            failures.append("search: sentinel missing")
    except requests.RequestException as e:
        print(f"FAIL ({e})")
        failures.append(f"search: {e}")

    # 5. Cleanup
    print("[5/5] cleanup test category …", end=" ")
    if args.skip_cleanup:
        print("SKIPPED (per --skip-cleanup)")
    else:
        try:
            r = requests.delete(
                f"{base}/memory",
                headers=h,
                params={"category": "test"},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            print("OK")
        except requests.RequestException as e:
            print(f"FAIL ({e})")
            failures.append(f"cleanup: {e}")

    # Final stats for sanity
    try:
        r = requests.get(f"{base}/brain/stats", headers=h, timeout=TIMEOUT)
        after = r.json().get("total_memories", 0)
        print(f"\nFinal: {before} → {after} memories")
    except requests.RequestException:
        pass

    if failures:
        print(f"\n❌ {len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\n✅ All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
