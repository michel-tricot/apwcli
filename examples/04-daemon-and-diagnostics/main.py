"""Explicit daemon control, health checks, and manual pairing.

Usage:

    uv run python examples/04-daemon-and-diagnostics/main.py

Most programs never need this — `ApplePasswords` auto-starts and auto-pairs.
Use `Daemon` when you want the lifecycle in your own hands (a setup step, a
health endpoint, a kiosk that pre-warms the daemon at boot, ...).
"""

from __future__ import annotations

import sys

from apwlib import Daemon, DaemonStartError
from apwlib.diagnostics import run_checks


def main() -> int:
    daemon = Daemon()

    # The same structured checks that back `apwcli doctor`.
    for check in run_checks(daemon):
        mark = "ok " if check.ok else ("FAIL" if check.required else "warn")
        print(f"[{mark}] {check.key}: {check.detail}" + (f"  ({check.hint})" if check.hint else ""))

    try:
        daemon.start()  # no-op if already running; raises if it can't come up
    except DaemonStartError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    status = daemon.status()
    print(f"daemon running with {status['browser']} (pid {status['browser_pid']})")

    if not status["paired"]:
        # Manual pairing: request the challenge (macOS displays the PIN), then
        # verify. verify_challenge blocks until the attempt settles.
        daemon.request_challenge()
        paired = daemon.verify_challenge(input("PIN shown by macOS: "))
        print("paired" if paired else "pairing failed (wrong PIN?)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
