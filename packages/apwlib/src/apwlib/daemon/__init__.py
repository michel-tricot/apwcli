"""The daemon: browser discovery, extension injection, and the socket/bridge server.

This subpackage holds everything that manages the headless browser. The client-facing
facade (``apwlib.ApplePasswords``) never imports it; it launches the daemon as a separate
process (``python -m apwlib.daemon``) and talks to it over the socket.
"""

# Browser discovery lives in apwlib.browsers (it's shared with pinwindow); re-exported
# here for compatibility.
from apwlib.browsers import (
    BROWSERS,
    Browser,
    installed_browsers,
    resolve_browser,
)
from apwlib.daemon.server import run

__all__ = [
    "BROWSERS",
    "Browser",
    "installed_browsers",
    "resolve_browser",
    "run",
]
