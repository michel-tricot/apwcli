"""Create or update a credential in Apple Passwords.

Usage:

    uv run python examples/03-save-password/main.py [url] <username>

The url defaults to github.com when only a username is given. The password is
prompted for (never passed on the command line, where it would be visible in
the shell history and `ps`).
"""

from __future__ import annotations

import getpass
import sys

from apwlib import ApplePasswords, ApwError
from apwlib.pinwindow import request_pin


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 1:
        url, username = "github.com", args[0]
    elif len(args) == 2:
        url, username = args
    else:
        print(f"usage: {sys.argv[0]} [url] <username>", file=sys.stderr)
        return 2

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
