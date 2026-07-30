"""Detached helper: clear the clipboard after a delay, if it still holds our secret.

Run as ``python -m apwcli._clipboard <seconds>`` with the secret on stdin. Kept as
its own module so the CLI can spawn it detached and exit immediately; the secret
travels over stdin (never argv/env, which are visible in ``ps``).
"""

from __future__ import annotations

import subprocess
import sys
import time


def clear_if_unchanged(secret: bytes) -> bool:
    """Clear the clipboard iff it still holds ``secret`` (don't clobber a later copy)."""
    current = subprocess.run(["pbpaste"], capture_output=True).stdout
    if current == secret:
        subprocess.run(["pbcopy"], input=b"", check=False)
        return True
    return False


def main() -> int:
    try:
        seconds = float(sys.argv[1])
    except (IndexError, ValueError):
        return 2
    secret = sys.stdin.buffer.read()
    if not secret:
        return 0
    time.sleep(seconds)
    clear_if_unchanged(secret)
    return 0


if __name__ == "__main__":
    sys.exit(main())
