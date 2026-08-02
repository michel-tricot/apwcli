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
from apwlib.protocol import WIRE_UNPAIRED, Status

_BACKGROUND = "background.js"
# Bounds how long an offline daemon start waits before falling back to the cache.
_STORE_TIMEOUT = 10.0
# chauffeur's default keep-alive (25s) only prevents eviction; this worker holds a
# live SRP session, and an idle worker drops the pairing handshake within ~5s
# (ChallengeSent -> NotInSession), so the poke must land well under that.
_WORKER_KEEP_ALIVE = 2.0
# The bridge's budget for one native-helper round trip, kept below the daemon's
# 30s request timeout (server.py) so the bridge times out first and replies.
_NATIVE_TIMEOUT_MS = 25_000


def extension_spec() -> ExtensionSpec:
    """The extension to load: store download + injected wire constants + the bridge.

    Pure declaration — no network or disk I/O until chauffeur builds it at launch.
    chauffeur gives the extension's service worker a ``py_chauffeur`` channel
    (``worker_channel`` defaults on), which the bridge uses to reach the daemon —
    so there is no socket config to inject — and keeps the worker awake
    (``keep_alive``) so the SRP handshake and paired session survive idle gaps.
    ``inject_config`` prepends the status codes and wire markers the bridge shares
    with the Python side, so ``protocol.py`` stays their single source of truth.
    """
    return (
        ExtensionSpec.from_store(
            EXTENSION_ID,
            refresh=True,
            timeout=_STORE_TIMEOUT,
            cache_dir=DATA_DIR,
            keep_alive=_WORKER_KEEP_ALIVE,
        )
        .inject_config(
            _BACKGROUND,
            {
                "statusOk": int(Status.SUCCESS),
                "statusInvalidParam": int(Status.INVALID_PARAM),
                "statusInvalidSession": int(Status.INVALID_SESSION),
                "statusServerError": int(Status.SERVER_ERROR),
                "nativeTimeoutMs": _NATIVE_TIMEOUT_MS,
                "wireUnpaired": WIRE_UNPAIRED,
            },
        )
        .append(_BACKGROUND, BRIDGE_JS)
    )
