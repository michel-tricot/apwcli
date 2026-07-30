"""Build a modified copy of the iCloud Passwords extension with the bridge injected."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from apwlib.browsers import find_extension_source
from apwlib.daemon.bridge import BRIDGE_JS
from apwlib.errors import ApwError
from apwlib.paths import EXTENSION_DIR, ensure_data_dir
from apwlib.protocol import Status

_BACKGROUND = "background.js"


def build_extension(port: int, token: str) -> Path:
    """Return a path to an unpacked extension whose background worker runs the bridge.

    The pristine extension is copied from the installed source (``background.js`` preserved
    as ``.orig``, the source's versioned path recorded in ``.source``); each build rewrites
    ``background.js`` as ``<orig> + APW_CONFIG + bridge``. The copy is refreshed when the
    installed extension's version changes, so an update to iCloud Passwords is picked up
    rather than frozen at first build.
    """
    ensure_data_dir()
    background = EXTENSION_DIR / _BACKGROUND
    original = EXTENSION_DIR / f"{_BACKGROUND}.orig"
    marker = EXTENSION_DIR / ".source"

    source = find_extension_source()  # a versioned dir path, or None if none is installed
    cached = marker.read_text().strip() if marker.exists() else None
    have_copy = original.exists()

    # (Re)copy when we have no cached copy, or the installed version differs from it.
    if not have_copy or (source is not None and str(source) != cached):
        if source is None:
            if not have_copy:
                raise ApwError(
                    Status.GENERIC_ERROR,
                    "iCloud Passwords extension not found. Install it in a supported browser "
                    "from the Chrome Web Store, open that browser once, then retry.",
                )
            # Can't locate an install right now (e.g. profile moved) — keep the cached copy.
        else:
            if EXTENSION_DIR.exists():
                shutil.rmtree(EXTENSION_DIR)
            shutil.copytree(source, EXTENSION_DIR)
            shutil.rmtree(EXTENSION_DIR / "_metadata", ignore_errors=True)
            shutil.copyfile(background, original)
            marker.write_text(str(source))

    config = json.dumps({"port": port, "token": token})
    background.write_text(f"{original.read_text()}\nself.APW_CONFIG = {config};\n{BRIDGE_JS}\n")
    return EXTENSION_DIR
