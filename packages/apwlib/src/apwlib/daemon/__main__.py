"""``python -m apwlib.daemon`` — run the daemon standalone (used by client auto-start).

Selects a browser from config (falling back to auto) and runs until stopped. If another
daemon already holds the singleton lock, this exits immediately.
"""

from __future__ import annotations

import asyncio
import sys

from apwlib.config import read_config
from apwlib.daemon import resolve_browser, run


def main() -> int:
    browser = resolve_browser(read_config().get("browser"))
    if browser is None:
        print("apwlib: no supported browser installed", file=sys.stderr)
        return 1
    asyncio.run(run(browser))
    return 0


if __name__ == "__main__":
    sys.exit(main())
