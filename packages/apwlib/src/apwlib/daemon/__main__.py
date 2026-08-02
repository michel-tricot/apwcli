"""``python -m apwlib.daemon [browser]`` — run the daemon standalone (used by client auto-start).

An explicit ``browser`` id argument wins; otherwise the config file's ``browser`` key,
falling back to auto. Runs until stopped. If another daemon already holds the
singleton lock, this exits immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

from apwlib._browsers import resolve_browser
from apwlib._config import read_config
from apwlib.daemon import run


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    selected = args[0] if args else read_config().get("browser")
    browser = resolve_browser(selected)
    if browser is None:
        what = f"browser not available: {selected}" if selected else "no supported browser installed"
        print(f"apwlib: {what}", file=sys.stderr)
        return 1
    # Ctrl-C during launch (before the loop's signal handlers are installed) still
    # lands here as KeyboardInterrupt; treat it as a clean stop, not a traceback.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(browser))
    return 0


if __name__ == "__main__":
    sys.exit(main())
