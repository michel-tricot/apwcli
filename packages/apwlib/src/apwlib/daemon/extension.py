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

    The pristine extension is copied once (``background.js`` preserved as ``.orig``); each
    build rewrites ``background.js`` as ``<orig> + APW_CONFIG + bridge``.
    """
    ensure_data_dir()
    background = EXTENSION_DIR / _BACKGROUND
    original = EXTENSION_DIR / f"{_BACKGROUND}.orig"

    if not original.exists():
        source = find_extension_source()
        if source is None:
            raise ApwError(
                Status.GENERIC_ERROR,
                "iCloud Passwords extension not found. Install it in a supported browser "
                "from the Chrome Web Store, open that browser once, then retry.",
            )
        if EXTENSION_DIR.exists():
            shutil.rmtree(EXTENSION_DIR)
        shutil.copytree(source, EXTENSION_DIR)
        shutil.rmtree(EXTENSION_DIR / "_metadata", ignore_errors=True)
        shutil.copyfile(background, original)

    config = json.dumps({"port": port, "token": token})
    background.write_text(f"{original.read_text()}\nself.APW_CONFIG = {config};\n{BRIDGE_JS}\n")
    return EXTENSION_DIR
