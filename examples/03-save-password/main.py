"""Create or update a credential in Apple Passwords.

Usage:

    uv run python examples/03-save-password/main.py example.com me@example.com

The password is prompted for (never passed on the command line, where it would
be visible in the shell history and `ps`).
"""

from __future__ import annotations

import getpass
import sys

from apwlib import ApplePasswords, ApwError
from apwlib.pinwindow import request_pin


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <url> <username>", file=sys.stderr)
        return 2
    url, username = sys.argv[1], sys.argv[2]

    pw = ApplePasswords(pin_provider=request_pin)
    try:
        pw.save_password(url, username, getpass.getpass("password: "))
    except ApwError as exc:
        print(f"error (status {int(exc.status)}): {exc}", file=sys.stderr)
        return int(exc.status)
    print(f"saved {username} @ {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
