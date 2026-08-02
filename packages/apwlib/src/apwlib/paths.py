"""Filesystem locations used by the daemon and client.

Everything lives under ``~/.apwlib`` (created mode 0700).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

DATA_DIR = Path("~/.apwlib").expanduser()
SOCKET_PATH = DATA_DIR / "apw.sock"
CONFIG_PATH = DATA_DIR / "config.json"
# The official iCloud Passwords Chrome extension, and where chauffeur caches its
# pristine store download (StoreExtension's <cache_dir>/<id>.src layout).
EXTENSION_ID = "pejdijmoenmkgeppbflobdenhhabjlaj"
EXTENSION_DIR = DATA_DIR / f"{EXTENSION_ID}.src"
BROWSER_PROFILE_DIR = DATA_DIR / "browser"
LOCK_PATH = DATA_DIR / "daemon.lock"
LOG_PATH = DATA_DIR / "daemon.log"
PIN_STYLE_PATH = DATA_DIR / "pinwindow.css"  # optional user override for the PIN window style

# Apple's native-messaging manifest, installed by macOS for Chromium browsers. We copy it
# into our managed browser profile so the loaded extension can reach the helper.
APPLE_NATIVE_MANIFEST = Path(
    "/Library/Google/Chrome/NativeMessagingHosts/com.apple.passwordmanager.json"
)


def cached_extension_version() -> str | None:
    """Version of the extension cached in ``EXTENSION_DIR``, or None before first fetch.

    Lives here (not in ``daemon/``) so status consumers like ``apwcli doctor`` can
    inspect the cache without importing the daemon implementation.
    """
    with contextlib.suppress(OSError, ValueError):
        manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
        version = manifest.get("version") if isinstance(manifest, dict) else None
        return str(version) if version else None
    return None


def ensure_data_dir() -> Path:
    """Create ``~/.apwlib`` (mode 0700) if needed and return it."""
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    return DATA_DIR
