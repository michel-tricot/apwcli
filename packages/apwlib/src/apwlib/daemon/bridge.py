"""Loads the JavaScript bridge injected into the extension's background worker.

The bridge source lives next door in ``bridge.js`` — edit it there with real JS tooling.
It is read once at import time and appended to the extension's background worker by
``extension.py``.
"""

from importlib.resources import files

BRIDGE_JS = files("apwlib.daemon").joinpath("bridge.js").read_text(encoding="utf-8")
