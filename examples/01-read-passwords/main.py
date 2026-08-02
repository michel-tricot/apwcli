"""List the accounts saved for a site, then read a password.

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
        accounts = pw.list_accounts(url)  # usernames only, never passwords
    except SessionError as exc:
        # Daemon unreachable or pairing declined — see `apwcli doctor`.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not accounts:
        print(f"no accounts saved for {url}")
        return 0

    print(f"accounts for {url}:")
    for account in accounts:
        print(f"  {account.username}")

    # Passwords are a separate, explicit read; narrow with a username or get all.
    for entry in pw.get_password(url, username):
        print(f"password for {entry.username}: {entry.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
