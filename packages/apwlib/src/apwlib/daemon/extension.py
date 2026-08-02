"""Describe the bridge-carrying iCloud Passwords extension for chauffeur to build.

The extension comes from the Chrome Web Store (no local browser install required):
``ExtensionSpec.from_store`` with ``refresh=True`` re-downloads on every build so
store updates are picked up, keeps the cached copy when the store is unreachable
(offline), and pins the pristine cache to ``EXTENSION_DIR`` so ``apwcli doctor``
can inspect it. The download runs when chauffeur resolves the source at build
time — inside its launch worker thread, so the daemon's event loop never blocks
on the store. A first-ever fetch that fails surfaces as ``ExtensionNotFoundError``
from the launch; the daemon translates it to ``ApwError`` (see server.py).
"""

from __future__ import annotations

from chauffeur import ExtensionSpec

from apwlib.daemon.bridge import BRIDGE_JS
from apwlib.paths import DATA_DIR, EXTENSION_ID

_BACKGROUND = "background.js"
# Bounds how long an offline daemon start waits before falling back to the cache.
_STORE_TIMEOUT = 10.0
# chauffeur's default keep-alive (25s) only prevents eviction; this worker holds a
# live SRP session, and an idle worker drops the pairing handshake within ~5s
# (ChallengeSent -> NotInSession), so the poke must land well under that.
_WORKER_KEEP_ALIVE = 2.0


def extension_spec() -> ExtensionSpec:
    """The extension to load: store download + the appended bridge.

    Pure declaration — no network or disk I/O until chauffeur builds it at launch.
    chauffeur gives the extension's service worker a ``py_chauffeur`` channel
    (``worker_channel`` defaults on), which the bridge uses to reach the daemon —
    so there is no socket config to inject — and keeps the worker awake
    (``keep_alive``) so the SRP handshake and paired session survive idle gaps.
    """
    return ExtensionSpec.from_store(
        EXTENSION_ID,
        refresh=True,
        timeout=_STORE_TIMEOUT,
        cache_dir=DATA_DIR,
        keep_alive=_WORKER_KEEP_ALIVE,
    ).append(_BACKGROUND, BRIDGE_JS)
