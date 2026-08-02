"""Read the password entries saved for a site.

Usage:

    uv run python examples/01-read-passwords/main.py github.com [username]

The first call auto-starts the background daemon. If the session isn't paired
yet, the ``pin_provider`` kicks in: macOS shows a 6-digit PIN and a small
on-screen window collects it (which also works when there is no terminal).
"""

from __future__ import annotations

import sys

from apwlib import ApplePasswords, SessionError
from apwlib.pinwindow import request_pin


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "github.com"
    username = sys.argv[2] if len(sys.argv) > 2 else None

    pw = ApplePasswords(pin_provider=request_pin)

    try:
        # Narrow with a username, or omit it for every entry saved for the site.
        entries = pw.get_password(url, username)
    except SessionError as exc:
        # Daemon unreachable or pairing declined — see `apwcli doctor`.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not entries:
        print(f"no entries saved for {url}")
        return 0

    for entry in entries:
        # entry.password holds the real value; keep it out of the terminal
        # (and its scrollback) — hand it to whatever needs it instead.
        redacted = "••••••••" if entry.password else "(no password)"
        print(f"{entry.username}: {redacted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
