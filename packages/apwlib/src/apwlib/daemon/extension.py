"""Describe the bridge-carrying iCloud Passwords extension for chauffeur to build.

The extension is downloaded from the Chrome Web Store by id (no local browser install
required) and cached pristine under ``EXTENSION_DIR``. Each daemon start re-downloads
so store updates are picked up; when the store is unreachable (offline) the cached
copy keeps working. chauffeur does the patching and building (into
``<profile>.extensions/`` at launch) and loads the result over CDP.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

from chauffeur import ExtensionSpec, download_extension
from chauffeur.extension import ExtensionNotFoundError

from apwlib.daemon.bridge import BRIDGE_JS
from apwlib.errors import ApwError
from apwlib.paths import EXTENSION_DIR, ensure_data_dir
from apwlib.protocol import Status

# The official iCloud Passwords Chrome extension.
EXTENSION_ID = "pejdijmoenmkgeppbflobdenhhabjlaj"
_BACKGROUND = "background.js"


def cached_extension_version() -> str | None:
    """Version of the cached store download, or None if nothing is cached yet."""
    with contextlib.suppress(OSError, ValueError):
        version = json.loads((EXTENSION_DIR / "manifest.json").read_text()).get("version")
        return str(version) if version else None
    return None


def _pristine_extension() -> Path:
    """Return a pristine copy of the extension, downloading/refreshing the cache."""
    ensure_data_dir()
    have_copy = (EXTENSION_DIR / "manifest.json").exists()
    try:
        download_extension(EXTENSION_ID, EXTENSION_DIR)  # replaces any prior contents
    except ExtensionNotFoundError as exc:
        if not have_copy:
            raise ApwError(
                Status.GENERIC_ERROR,
                "could not download the iCloud Passwords extension from the "
                f"Chrome Web Store: {exc}",
            ) from exc
        # Store unreachable (e.g. offline) — the cached copy keeps working.
    else:
        # Chrome refuses to load an unpacked extension containing _metadata.
        shutil.rmtree(EXTENSION_DIR / "_metadata", ignore_errors=True)
    return EXTENSION_DIR


def extension_spec(port: int, token: str) -> ExtensionSpec:
    """The extension to load: pristine copy + injected bridge config + the bridge itself."""
    return (
        ExtensionSpec(_pristine_extension())
        .inject_config(_BACKGROUND, {"port": port, "token": token})
        .append(_BACKGROUND, BRIDGE_JS)
    )
