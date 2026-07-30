"""Filesystem locations used by the daemon and client.

Everything lives under ``~/.apwlib`` (created mode 0700).
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.path.expanduser("~/.apwlib"))
SOCKET_PATH = DATA_DIR / "apw.sock"
CONFIG_PATH = DATA_DIR / "config.json"
EXTENSION_DIR = DATA_DIR / "extension"
BROWSER_PROFILE_DIR = DATA_DIR / "browser"
LOCK_PATH = DATA_DIR / "daemon.lock"
LOG_PATH = DATA_DIR / "daemon.log"
PIN_STYLE_PATH = DATA_DIR / "pinwindow.css"  # optional user override for the PIN window style

# Apple's native-messaging manifest, installed by macOS for Chromium browsers. We copy it
# into our managed browser profile so the loaded extension can reach the helper.
APPLE_NATIVE_MANIFEST = Path(
    "/Library/Google/Chrome/NativeMessagingHosts/com.apple.passwordmanager.json"
)


def ensure_data_dir() -> Path:
    """Create ``~/.apwlib`` (mode 0700) if needed and return it."""
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DATA_DIR.chmod(0o700)
    return DATA_DIR
