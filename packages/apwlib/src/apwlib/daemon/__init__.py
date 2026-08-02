"""The daemon: browser discovery, extension injection, and the socket/bridge server.

This subpackage holds everything that manages the headless browser. The client-facing
facade (``apwlib.ApplePasswords``) never imports it; it launches the daemon as a separate
process (``python -m apwlib.daemon``) and talks to it over the socket.
"""

from apwlib.daemon.server import run

__all__ = ["run"]
