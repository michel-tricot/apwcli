"""Read one-time (2FA) codes for a site.

Usage:

    uv run python examples/02-one-time-codes/main.py github.com
"""

from __future__ import annotations

import sys

from apwlib import ApplePasswords
from apwlib.pinwindow import request_pin


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "github.com"
    pw = ApplePasswords(pin_provider=request_pin)

    # list_otp: which accounts have codes (no code values).
    holders = pw.list_otp(url)
    if not holders:
        print(f"no one-time codes set up for {url}")
        return 0
    print(f"accounts with codes for {url}: " + ", ".join(e.username for e in holders))

    # get_otp: the current code(s). They rotate every ~30 seconds.
    for entry in pw.get_otp(url):
        print(f"{entry.username}: {entry.code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
