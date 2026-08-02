"""``python -m apwlib.daemon`` — run the daemon standalone (used by client auto-start).

Selects a browser from config (falling back to auto) and runs until stopped. If another
daemon already holds the singleton lock, this exits immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

from apwlib.browsers import resolve_browser
from apwlib.config import read_config
from apwlib.daemon import run


def main() -> int:
    browser = resolve_browser(read_config().get("browser"))
    if browser is None:
        print("apwlib: no supported browser installed", file=sys.stderr)
        return 1
    # Ctrl-C during launch (before the loop's signal handlers are installed) still
    # lands here as KeyboardInterrupt; treat it as a clean stop, not a traceback.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(browser))
    return 0


if __name__ == "__main__":
    sys.exit(main())
